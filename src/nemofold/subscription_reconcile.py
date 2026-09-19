"""Subscription reconciliation with message evidence (Gate G06, Ellmos UC 11).

Deterministic reconciliation between declared subscriptions and observed message/invoice
evidence. Detects price discrepancies, status mismatches (e.g. cancellation confirmations),
and fail-closed blocks when ambiguous matches occur.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .artifacts import write_text_artifact
from .case_chronicle import ChronicleInput, _coverage, _json_artifact
from .completeness import Question, needs_input_payload
from .contracts import ArtifactRecord, Claim, Coverage, EvidenceLocator, WorkflowBlocked
from .primitives import Anchor
from .report_studio import ReportDocument, render_report_formats

RECONCILIATION_SCHEMA = "nemofold.subscription-reconciliation.v1"

CANCELLATION_KEYWORDS = frozenset(
    {
        "gekündigt",
        "kündigung",
        "kündigungsbestätigung",
        "vertragsende",
        "beendigung",
        "abgemeldet",
        "deaktiviert",
        "cancelled",
        "cancellation",
        "terminated",
    }
)

ACTIVE_KEYWORDS = frozenset(
    {
        "aktiv",
        "laufend",
        "aktiviert",
        "active",
        "verlängert",
        "erneuert",
        "renewed",
    }
)


@dataclass(frozen=True, slots=True)
class SubscriptionRecord:
    """A declared subscription item."""

    name: str
    amount: float | None
    amount_raw: str
    cadence: str
    status: str  # active, inactive, cancelled, unknown
    account_id: str | None
    anchor: Anchor
    quote: str


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """A message or invoice evidence item."""

    sender: str
    subject: str
    date: str | None
    amount: float | None
    amount_raw: str | None
    body: str
    account_id: str | None
    anchor: Anchor
    quote: str


@dataclass(frozen=True, slots=True)
class MatchDiscrepancy:
    """A detected discrepancy between declaration and evidence."""

    kind: str  # price_change, status_mismatch, unconfirmed
    description: str
    declared_value: str
    evidence_value: str


@dataclass(frozen=True, slots=True)
class ReconciliationMatch:
    """Reconciliation result for one subscription."""

    subscription: SubscriptionRecord
    matched_message: MessageRecord | None
    status: str  # reconciled, discrepancy, unconfirmed, ambiguous
    discrepancies: tuple[MatchDiscrepancy, ...] = ()
    evidence_quote: str = ""
    evidence_source_id: str = ""
    evidence_line: int = 0
    match_confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    """Overall outcome of subscription reconciliation."""

    matches: tuple[ReconciliationMatch, ...]
    unmatched_messages: tuple[MessageRecord, ...]
    ambiguous_matches: tuple[tuple[SubscriptionRecord, tuple[MessageRecord, ...]], ...]
    total_declared: int
    total_reconciled: int
    total_discrepancies: int
    total_unconfirmed: int
    total_ambiguous: int


def _parse_amount(raw: str) -> float | None:
    if not raw:
        return None
    cleaned = raw.strip()
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", cleaned)
    if not match:
        return None
    token = match.group(0)
    if "," in token and "." in token:
        token = token.replace(".", "").replace(",", ".")
    elif "," in token:
        token = token.replace(",", ".")
    try:
        val = Decimal(token)
        return float(val)
    except (InvalidOperation, ValueError):
        return None


def _normalize_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", name.casefold())
    return " ".join(cleaned.split())


def extract_subscriptions_from_texts(
    source_ids: Sequence[str],
    texts: dict[str, str],
    *,
    sub_marker: str = "Abo",
    amount_marker: str = "Betrag",
    cadence_marker: str = "Turnus",
    status_marker: str = "Status",
    account_marker: str = "Konto",
) -> list[SubscriptionRecord]:
    """Extract declared subscription records from structured text files."""
    subs: list[SubscriptionRecord] = []
    for sid in source_ids:
        text = texts.get(sid, "")
        lines = text.splitlines()
        current_sub: dict[str, tuple[str, int]] = {}
        for line_num, line in enumerate(lines, start=1):
            if not line.strip():
                if sub_marker in current_sub:
                    sub_name, s_line = current_sub[sub_marker]
                    amt_raw, _ = current_sub.get(amount_marker, ("", s_line))
                    cad, _ = current_sub.get(cadence_marker, ("monatlich", s_line))
                    st, _ = current_sub.get(status_marker, ("aktiv", s_line))
                    acc, _ = current_sub.get(account_marker, ("", s_line))
                    quote = " · ".join(f"{k}: {v[0]}" for k, v in current_sub.items())
                    subs.append(
                        SubscriptionRecord(
                            name=sub_name,
                            amount=_parse_amount(amt_raw),
                            amount_raw=amt_raw,
                            cadence=cad.lower(),
                            status=st.lower(),
                            account_id=acc if acc else None,
                            anchor=Anchor(source_id=sid, line=s_line),
                            quote=quote,
                        )
                    )
                current_sub = {}
                continue

            for marker in (
                sub_marker,
                amount_marker,
                cadence_marker,
                status_marker,
                account_marker,
            ):
                pattern = re.compile(
                    rf"^\s*{re.escape(marker)}\s*:\s*(?P<val>\S.*?)\s*$", re.IGNORECASE
                )
                m = pattern.match(line)
                if m:
                    current_sub[marker] = (m.group("val").strip(), line_num)
                    break

        if sub_marker in current_sub:
            sub_name, s_line = current_sub[sub_marker]
            amt_raw, _ = current_sub.get(amount_marker, ("", s_line))
            cad, _ = current_sub.get(cadence_marker, ("monatlich", s_line))
            st, _ = current_sub.get(status_marker, ("aktiv", s_line))
            acc, _ = current_sub.get(account_marker, ("", s_line))
            quote = " · ".join(f"{k}: {v[0]}" for k, v in current_sub.items())
            subs.append(
                SubscriptionRecord(
                    name=sub_name,
                    amount=_parse_amount(amt_raw),
                    amount_raw=amt_raw,
                    cadence=cad.lower(),
                    status=st.lower(),
                    account_id=acc if acc else None,
                    anchor=Anchor(source_id=sid, line=s_line),
                    quote=quote,
                )
            )
    return subs


def extract_messages_from_texts(
    source_ids: Sequence[str],
    texts: dict[str, str],
    *,
    sender_marker: str = "Absender",
    subject_marker: str = "Betreff",
    date_marker: str = "Datum",
    amount_marker: str = "Betrag",
    account_marker: str = "Konto",
) -> list[MessageRecord]:
    """Extract message / invoice evidence records from message text files."""
    messages: list[MessageRecord] = []
    for sid in source_ids:
        text = texts.get(sid, "")
        lines = text.splitlines()
        fields: dict[str, tuple[str, int]] = {}
        body_lines: list[str] = []
        is_body = False
        start_line = 1
        for line_num, line in enumerate(lines, start=1):
            if is_body:
                body_lines.append(line)
                continue
            if not line.strip():
                is_body = True
                continue

            matched = False
            for marker in (
                sender_marker,
                subject_marker,
                date_marker,
                amount_marker,
                account_marker,
            ):
                pattern = re.compile(
                    rf"^\s*{re.escape(marker)}\s*:\s*(?P<val>\S.*?)\s*$", re.IGNORECASE
                )
                m = pattern.match(line)
                if m:
                    fields[marker] = (m.group("val").strip(), line_num)
                    matched = True
                    break
            if not matched:
                is_body = True
                body_lines.append(line)

        if fields:
            sender, s_line = fields.get(sender_marker, ("Unbekannt", start_line))
            subject, _ = fields.get(subject_marker, ("", s_line))
            date_val, _ = fields.get(date_marker, ("", s_line))
            amt_raw, _ = fields.get(amount_marker, ("", s_line))
            acc, _ = fields.get(account_marker, ("", s_line))
            body_text = "\n".join(body_lines).strip()
            quote_parts = [f"{k}: {v[0]}" for k, v in fields.items()]
            if body_text:
                quote_parts.append(f"Text: {body_text[:80]}")
            messages.append(
                MessageRecord(
                    sender=sender,
                    subject=subject,
                    date=date_val if date_val else None,
                    amount=_parse_amount(amt_raw) if amt_raw else None,
                    amount_raw=amt_raw if amt_raw else None,
                    body=body_text,
                    account_id=acc if acc else None,
                    anchor=Anchor(source_id=sid, line=s_line),
                    quote=" · ".join(quote_parts),
                )
            )
    return messages


def reconcile_subscriptions(
    subscriptions: list[SubscriptionRecord],
    messages: list[MessageRecord],
) -> ReconciliationSummary:
    """Match declared subscriptions against message evidence and detect discrepancies."""
    matches: list[ReconciliationMatch] = []
    used_messages: set[int] = set()
    ambiguous_list: list[tuple[SubscriptionRecord, tuple[MessageRecord, ...]]] = []

    # Map candidate scores: (sub_idx, msg_idx) -> score
    cand_msgs_for_sub: dict[int, list[tuple[int, MessageRecord, float]]] = {
        i: [] for i in range(len(subscriptions))
    }
    cand_subs_for_msg: dict[int, list[tuple[int, SubscriptionRecord, float]]] = {
        j: [] for j in range(len(messages))
    }

    for sub_idx, sub in enumerate(subscriptions):
        sub_norm = _normalize_name(sub.name)
        sub_tokens = set(sub_norm.split())

        for msg_idx, msg in enumerate(messages):
            score = 0.0
            searchable = f"{msg.sender} {msg.subject} {msg.body}".casefold()
            searchable_norm = _normalize_name(searchable)

            # Check account ID match
            if sub.account_id and msg.account_id:
                if sub.account_id.strip().casefold() == msg.account_id.strip().casefold():
                    score += 10.0
                else:
                    # Explicit conflicting account ID
                    continue

            # Check exact name containment
            if sub_norm in searchable_norm:
                score += 5.0
            else:
                # Token overlap
                matched_tokens = sub_tokens.intersection(searchable_norm.split())
                if matched_tokens and sub_tokens:
                    score += len(matched_tokens) / len(sub_tokens) * 3.0

            # Amount reinforcement
            if (
                sub.amount is not None
                and msg.amount is not None
                and abs(sub.amount - msg.amount) <= 0.01
            ):
                score += 1.0

            if score >= 2.0:
                cand_msgs_for_sub[sub_idx].append((msg_idx, msg, score))
                cand_subs_for_msg[msg_idx].append((sub_idx, sub, score))

    # Sort candidate lists by score descending
    for sub_idx in cand_msgs_for_sub:
        cand_msgs_for_sub[sub_idx].sort(key=lambda c: c[2], reverse=True)
    for msg_idx in cand_subs_for_msg:
        cand_subs_for_msg[msg_idx].sort(key=lambda c: c[2], reverse=True)

    # Track subscriptions with ambiguous matches
    ambiguous_sub_evidence: dict[int, list[MessageRecord]] = {}

    # Direction 1: One message matches multiple subscriptions without account differentiation
    for msg_idx, sub_cands in cand_subs_for_msg.items():
        if len(sub_cands) > 1:
            top_score = sub_cands[0][2]
            sub_competing = [c for c in sub_cands if c[2] >= top_score - 1.5]
            if len(sub_competing) > 1:
                msg = messages[msg_idx]
                has_unique_acc = False
                if msg.account_id:
                    sub_matched_acc = [
                        c
                        for c in sub_competing
                        if c[1].account_id
                        and c[1].account_id.strip().casefold() == msg.account_id.strip().casefold()
                    ]
                    if len(sub_matched_acc) == 1:
                        has_unique_acc = True
                if not has_unique_acc:
                    for c in sub_competing:
                        ambiguous_sub_evidence.setdefault(c[0], []).append(msg)

    # Direction 2: One subscription matches multiple messages without account differentiation
    for sub_idx, msg_cands in cand_msgs_for_sub.items():
        if len(msg_cands) > 1:
            top_score = msg_cands[0][2]
            msg_competing = [c for c in msg_cands if c[2] >= top_score - 0.5]
            if len(msg_competing) > 1:
                sub = subscriptions[sub_idx]
                has_unique_acc = False
                if sub.account_id:
                    msg_matched_acc = [
                        c
                        for c in msg_competing
                        if c[1].account_id
                        and c[1].account_id.strip().casefold() == sub.account_id.strip().casefold()
                    ]
                    if len(msg_matched_acc) == 1:
                        has_unique_acc = True
                if not has_unique_acc:
                    ambiguous_sub_evidence.setdefault(sub_idx, []).extend(
                        c[1] for c in msg_competing
                    )

    # Evaluate each subscription
    for sub_idx, sub in enumerate(subscriptions):
        if sub_idx in ambiguous_sub_evidence:
            competing_msgs = tuple(dict.fromkeys(ambiguous_sub_evidence[sub_idx]))
            ambiguous_list.append((sub, competing_msgs))
            matches.append(
                ReconciliationMatch(
                    subscription=sub,
                    matched_message=None,
                    status="ambiguous",
                    discrepancies=(
                        MatchDiscrepancy(
                            kind="ambiguous_match",
                            description=(
                                f"Mehrdeutige Zuordnung für Abo '{sub.name}': "
                                f"{len(competing_msgs)} Belege/Abonnements "
                                "ohne eindeutiges Unterscheidungsmerkmal."
                            ),
                            declared_value=sub.name,
                            evidence_value=f"{len(competing_msgs)} Belege",
                        ),
                    ),
                    match_confidence=0.0,
                )
            )
            continue

        cands = cand_msgs_for_sub[sub_idx]
        if not cands:
            # Unconfirmed: no message evidence found
            matches.append(
                ReconciliationMatch(
                    subscription=sub,
                    matched_message=None,
                    status="unconfirmed",
                    discrepancies=(
                        MatchDiscrepancy(
                            kind="no_evidence",
                            description=f"Kein Nachrichtenbeleg für Abo '{sub.name}' gefunden.",
                            declared_value=sub.name,
                            evidence_value="fehlt",
                        ),
                    ),
                    match_confidence=0.0,
                )
            )
            continue

        best_idx, best_msg, confidence = cands[0]
        if best_idx in used_messages:
            # Message already consumed by another subscription without
            # prior disambiguation -> ambiguous
            ambiguous_list.append((sub, (best_msg,)))
            matches.append(
                ReconciliationMatch(
                    subscription=sub,
                    matched_message=None,
                    status="ambiguous",
                    discrepancies=(
                        MatchDiscrepancy(
                            kind="ambiguous_match",
                            description=(
                                f"Mehrdeutige Zuordnung für Abo '{sub.name}': "
                                f"Nachrichtenbeleg '{best_msg.subject}' wird bereits "
                                "von einem anderen Abo beansprucht."
                            ),
                            declared_value=sub.name,
                            evidence_value=best_msg.subject,
                        ),
                    ),
                    match_confidence=0.0,
                )
            )
            continue

        used_messages.add(best_idx)

        # Check discrepancies between declared sub and message
        discrepancies: list[MatchDiscrepancy] = []

        # 1. Price check
        if (
            sub.amount is not None
            and best_msg.amount is not None
            and abs(sub.amount - best_msg.amount) > 0.01
        ):
            discrepancies.append(
                MatchDiscrepancy(
                    kind="price_change",
                    description=(
                        f"Preisabweichung bei '{sub.name}': "
                        f"Hinterlegt {sub.amount:.2f} €, "
                        f"Beleg weist {best_msg.amount:.2f} € aus."
                    ),
                    declared_value=f"{sub.amount:.2f} €",
                    evidence_value=f"{best_msg.amount:.2f} €",
                )
            )

        # 2. Cancellation / status check
        msg_text = f"{best_msg.subject} {best_msg.body}".casefold()
        has_cancellation = any(kw in msg_text for kw in CANCELLATION_KEYWORDS)
        if has_cancellation and sub.status in ("aktiv", "active"):
            discrepancies.append(
                MatchDiscrepancy(
                    kind="status_mismatch",
                    description=(
                        f"Status-Diskrepanz bei '{sub.name}': "
                        "Hinterlegt als aktiv, aber Nachricht belegt Kündigung/Vertragsende."
                    ),
                    declared_value=sub.status,
                    evidence_value="Kündigung / Beendigung",
                )
            )

        status = "discrepancy" if discrepancies else "reconciled"
        matches.append(
            ReconciliationMatch(
                subscription=sub,
                matched_message=best_msg,
                status=status,
                discrepancies=tuple(discrepancies),
                evidence_quote=best_msg.quote,
                evidence_source_id=best_msg.anchor.source_id,
                evidence_line=best_msg.anchor.line,
                match_confidence=confidence,
            )
        )

    unmatched = tuple(msg for idx, msg in enumerate(messages) if idx not in used_messages)

    reconciled_count = sum(1 for m in matches if m.status == "reconciled")
    discrepancy_count = sum(1 for m in matches if m.status == "discrepancy")
    unconfirmed_count = sum(1 for m in matches if m.status == "unconfirmed")
    ambiguous_count = sum(1 for m in matches if m.status == "ambiguous")

    return ReconciliationSummary(
        matches=tuple(matches),
        unmatched_messages=unmatched,
        ambiguous_matches=tuple(ambiguous_list),
        total_declared=len(subscriptions),
        total_reconciled=reconciled_count,
        total_discrepancies=discrepancy_count,
        total_unconfirmed=unconfirmed_count,
        total_ambiguous=ambiguous_count,
    )


def execute_subscription_reconcile(
    job: Any,
    data: ChronicleInput,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    """Execute subscription reconciliation between declared contracts and messages.

    Fail-closed policy:
    - If require_unambiguous_matches is True and any ambiguous matches occur, raises WorkflowBlocked
      with needs-user-input rather than guessing.
    - If auto_status_change is requested on ambiguous items, halts with WorkflowBlocked.
    """
    subs = extract_subscriptions_from_texts(
        data.source_ids,
        data.texts,
        sub_marker=str(job.parameters.get("sub_marker", "Abo")),
        amount_marker=str(job.parameters.get("amount_marker", "Betrag")),
        cadence_marker=str(job.parameters.get("cadence_marker", "Turnus")),
        status_marker=str(job.parameters.get("status_marker", "Status")),
        account_marker=str(job.parameters.get("account_marker", "Konto")),
    )
    messages = extract_messages_from_texts(
        data.source_ids,
        data.texts,
        sender_marker=str(job.parameters.get("sender_marker", "Absender")),
        subject_marker=str(job.parameters.get("subject_marker", "Betreff")),
        date_marker=str(job.parameters.get("date_marker", "Datum")),
        amount_marker=str(job.parameters.get("amount_marker", "Betrag")),
        account_marker=str(job.parameters.get("account_marker", "Konto")),
    )

    output = Path(job.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    min_subs = int(job.parameters.get("min_subscriptions", 1))
    if len(subs) < min_subs:
        question = Question(
            field="subscriptions",
            prompt=(
                f"Zu wenige Abonnements gefunden ({len(subs)} < {min_subs}). "
                "Bitte deklarieren Sie Abos."
            ),
            why="Der Abo-Abgleich verlangt mindestens die deklarierte Anzahl an Abonnements.",
            kind="text",
        )
        asked = needs_input_payload((question,), workflow=job.workflow)
        needs_art = write_text_artifact(
            output / f"{run_id}.needs-user-input.json",
            json.dumps(asked, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "needs-user-input",
        )
        raise WorkflowBlocked(
            (f"insufficient_subscriptions:{len(subs)}<{min_subs}",),
            actions=(f"analyzed {len(data.source_ids)} source(s)", "subscriptions_insufficient"),
            artifacts=(needs_art,),
            coverage=_coverage(data, set()),
            metadata={"sub_count": len(subs), "target_min": min_subs, "needs_user_input": True},
        )

    summary = reconcile_subscriptions(subs, messages)

    # Fail-closed ambiguity gate
    require_unambiguous = bool(job.parameters.get("require_unambiguous_matches", True))
    if require_unambiguous and summary.total_ambiguous > 0:
        questions: list[Question] = []
        for sub, competing in summary.ambiguous_matches:
            candidates_info = "; ".join(f"{c.sender} ({c.quote[:40]})" for c in competing)
            questions.append(
                Question(
                    field=f"ambiguous_sub_{_normalize_name(sub.name)}",
                    prompt=(
                        f"Uneindeutige Zuordnung für Abo '{sub.name}'. "
                        f"Gefundene Belege: {candidates_info}. "
                        "Bitte geben Sie das korrekte Konto oder die Kennung an."
                    ),
                    why=(
                        "Uneindeutige Zuordnungen bleiben unbestätigt und lösen keine "
                        "Statusänderung aus. Ohne Klärung kann kein verlässlicher "
                        "Abgleich erfolgen."
                    ),
                    kind="text",
                )
            )
        asked = needs_input_payload(tuple(questions), workflow=job.workflow)
        needs_art = write_text_artifact(
            output / f"{run_id}.needs-user-input.json",
            json.dumps(asked, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "needs-user-input",
        )
        raise WorkflowBlocked(
            (f"ambiguous_subscription_matches:{summary.total_ambiguous}",),
            actions=(f"analyzed {len(data.source_ids)} source(s)", "ambiguous_matches_blocked"),
            artifacts=(needs_art,),
            coverage=_coverage(data, set()),
            metadata={
                "ambiguous_count": summary.total_ambiguous,
                "needs_user_input": True,
                "outcome_note": asked["outcome_note"],
            },
        )

    # Build claims
    claims: list[Claim] = []
    cited_sources: set[str] = set()

    for m in summary.matches:
        cited_sources.add(m.subscription.anchor.source_id)
        if m.status == "reconciled":
            evidence = m.matched_message
            if evidence is None:
                raise ValueError(
                    f"reconciled_match_without_message:{m.subscription.name}"
                )
            stmt = (
                f"Abo '{m.subscription.name}': Bestätigt durch Beleg von "
                f"{evidence.sender} ({m.subscription.amount_raw})."
            )
            locators = [
                EvidenceLocator(
                    source_id=m.subscription.anchor.source_id,
                    quote=m.subscription.quote,
                    section=f"line {m.subscription.anchor.line}",
                ),
                EvidenceLocator(
                    source_id=evidence.anchor.source_id,
                    quote=evidence.quote,
                    section=f"line {evidence.anchor.line}",
                ),
            ]
            cited_sources.add(evidence.anchor.source_id)
        elif m.status == "discrepancy":
            disc_text = "; ".join(d.description for d in m.discrepancies)
            stmt = f"Abo '{m.subscription.name}': Abweichung erkannt: {disc_text}"
            locators = [
                EvidenceLocator(
                    source_id=m.subscription.anchor.source_id,
                    quote=m.subscription.quote,
                    section=f"line {m.subscription.anchor.line}",
                ),
            ]
            if m.matched_message:
                locators.append(
                    EvidenceLocator(
                        source_id=m.matched_message.anchor.source_id,
                        quote=m.matched_message.quote,
                        section=f"line {m.matched_message.anchor.line}",
                    )
                )
                cited_sources.add(m.matched_message.anchor.source_id)
        else:
            stmt = f"Abo '{m.subscription.name}': Kein Beleg in aktuellen Nachrichten gefunden."
            locators = [
                EvidenceLocator(
                    source_id=m.subscription.anchor.source_id,
                    quote=m.subscription.quote,
                    section=f"line {m.subscription.anchor.line}",
                ),
            ]
        claims.append(Claim(statement=stmt, evidence=tuple(locators)))

    coverage = _coverage(data, cited_sources)

    # JSON reconciliation payload
    payload = {
        "schema": RECONCILIATION_SCHEMA,
        "title": str(job.parameters.get("title", "Abo-Abgleich mit Nachrichten")),
        "total_declared": summary.total_declared,
        "total_reconciled": summary.total_reconciled,
        "total_discrepancies": summary.total_discrepancies,
        "total_unconfirmed": summary.total_unconfirmed,
        "total_ambiguous": summary.total_ambiguous,
        "matches": [
            {
                "subscription": {
                    "name": m.subscription.name,
                    "amount": m.subscription.amount,
                    "amount_raw": m.subscription.amount_raw,
                    "cadence": m.subscription.cadence,
                    "status": m.subscription.status,
                    "account_id": m.subscription.account_id,
                    "anchor": {
                        "source_id": m.subscription.anchor.source_id,
                        "line": m.subscription.anchor.line,
                    },
                },
                "matched_message": {
                    "sender": m.matched_message.sender,
                    "subject": m.matched_message.subject,
                    "date": m.matched_message.date,
                    "amount": m.matched_message.amount,
                    "amount_raw": m.matched_message.amount_raw,
                    "anchor": {
                        "source_id": m.matched_message.anchor.source_id,
                        "line": m.matched_message.anchor.line,
                    },
                }
                if m.matched_message
                else None,
                "status": m.status,
                "discrepancies": [
                    {
                        "kind": d.kind,
                        "description": d.description,
                        "declared_value": d.declared_value,
                        "evidence_value": d.evidence_value,
                    }
                    for d in m.discrepancies
                ],
                "confidence": m.match_confidence,
            }
            for m in summary.matches
        ],
        "no_status_change_on_ambiguity_rule": (
            "Uneindeutige Zuordnungen bleiben unbestätigt und lösen keine Statusänderung aus."
        ),
    }

    json_art = _json_artifact(
        output, f"{run_id}.reconciliation.json", payload, "subscription-reconciliation"
    )
    report_formats = tuple(job.parameters.get("formats", ["md"]))
    doc = ReportDocument(
        title=str(job.parameters.get("title", "Abo-Abgleich mit Nachrichten")),
        claims=tuple(claims),
        coverage=coverage,
        scope_notice=(
            "Dieser Abgleich basiert ausschließlich auf den vorgelegten Dokumenten "
            "und Nachrichten. Uneindeutige Zuordnungen wurden unbestätigt belassen "
            "und führen zu keinen automatischen Statusänderungen."
        ),
    )
    rendered_arts = render_report_formats(
        doc,
        output,
        basename=f"{run_id}_reconciliation_report",
        formats=report_formats,
    )

    artifacts = (json_art, *rendered_arts)
    actions = (
        f"reconciled {summary.total_declared} subscription(s) against {len(messages)} message(s)",
        f"confirmed {summary.total_reconciled}, discrepancies {summary.total_discrepancies}",
    )
    metadata: dict[str, object] = {
        "total_declared": summary.total_declared,
        "total_reconciled": summary.total_reconciled,
        "total_discrepancies": summary.total_discrepancies,
        "total_unconfirmed": summary.total_unconfirmed,
        "total_ambiguous": summary.total_ambiguous,
        "discrepancies": [
            {"sub": m.subscription.name, "kind": d.kind, "desc": d.description}
            for m in summary.matches
            for d in m.discrepancies
        ],
    }

    return actions, artifacts, coverage, metadata
