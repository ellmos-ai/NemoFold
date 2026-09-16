"""Medication plan consolidation and reconciliation (Gate G07, Ellmos UC 23, 37).

Deterministic consolidation of medication plans across multiple medical reports, doctor letters,
and discharge summaries. Detects conflicting dosages, inconsistent schedules, status discrepancies,
and duplicate active ingredients. Strict fail-closed policy: conflicting dosages cannot be
automatically decided and require user/physician confirmation without medical overreach.
"""

from __future__ import annotations

import json
import re
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

MEDICATION_RECONCILIATION_SCHEMA = "nemofold.medication-reconciliation.v1"

MEDICAL_NON_AUTHORITY_NOTICE = (
    "HINWEIS: Dieser konsolidierte Medikationsplan dient ausschließlich der "
    "strukturierten Dokumentenübersicht und Information. Er ersetzt keine ärztliche "
    "oder pharmazeutische Beratung. Änderungen oder Festlegungen von Dosierungen "
    "dürfen ausschließlich durch medizinisches Fachpersonal erfolgen."
)


@dataclass(frozen=True, slots=True)
class MedicationRecord:
    """An individual medication record extracted from a medical document."""

    name: str
    active_ingredient: str | None
    dosage: str
    dosage_numeric: float | None
    dosage_unit: str
    schedule: str
    indication: str | None
    status: str  # laufend, pausiert, abgesetzt, bedarf
    date: str | None
    doctor: str | None
    anchor: Anchor
    quote: str


@dataclass(frozen=True, slots=True)
class MedicationConflict:
    """A detected conflict between multiple records for a medication or active ingredient."""

    kind: str  # conflicting_dosages, conflicting_schedules, duplicate_active_ingredient
    medication_name: str
    description: str
    competing_records: tuple[MedicationRecord, ...]
    resolved: bool = False
    resolution_note: str = ""
    resolved_by: str = ""


@dataclass(frozen=True, slots=True)
class ConsolidatedMedication:
    """A reconciled medication entry combining evidence across all sources."""

    name: str
    active_ingredient: str | None
    dosage: str
    dosage_numeric: float | None
    dosage_unit: str
    schedule: str
    indication: str | None
    status: str
    records: tuple[MedicationRecord, ...]
    conflict: MedicationConflict | None = None
    resolution_note: str | None = None
    source_anchors: tuple[Anchor, ...] = ()
    sources_summary: str = ""


@dataclass(frozen=True, slots=True)
class MedicationReconciliationSummary:
    """Overall outcome of medication plan reconciliation."""

    consolidated: tuple[ConsolidatedMedication, ...]
    conflicts: tuple[MedicationConflict, ...]
    unresolved_conflicts: tuple[MedicationConflict, ...]
    total_medications: int
    total_sources: int
    unresolved_conflict_count: int
    resolved_conflict_count: int
    duplicate_ingredient_count: int
    has_blocking_conflicts: bool
    medical_disclaimer: str = MEDICAL_NON_AUTHORITY_NOTICE


def _parse_dosage(raw: str) -> tuple[float | None, str]:
    """Parse a dosage string into numeric amount and unit."""
    if not raw:
        return None, ""
    cleaned = raw.strip()
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", cleaned)
    if not match:
        return None, cleaned
    num_str = match.group(0)
    token = num_str
    if "," in token and "." in token:
        token = token.replace(".", "").replace(",", ".")
    elif "," in token:
        token = token.replace(",", ".")
    try:
        val = float(Decimal(token))
    except (InvalidOperation, ValueError):
        val = None

    # Unit is the remainder
    unit = cleaned.replace(num_str, "").strip()
    return val, unit


def _normalize_med_name(name: str) -> str:
    """Canonical key for grouping medication names."""
    cleaned = re.sub(r"[^\w\s-]", " ", name.casefold())
    return " ".join(cleaned.split())


def _normalize_ingredient(ingredient: str | None) -> str | None:
    """Canonical key for active ingredients."""
    if not ingredient:
        return None
    cleaned = re.sub(r"[^\w\s-]", " ", ingredient.casefold())
    normalized = " ".join(cleaned.split())
    return normalized if normalized else None


def extract_medications_from_texts(
    source_ids: list[str],
    texts: dict[str, str],
    *,
    medication_marker: str = "Medikament",
    ingredient_marker: str = "Wirkstoff",
    dosage_marker: str = "Dosierung",
    schedule_marker: str = "Einnahme",
    indication_marker: str = "Indikation",
    status_marker: str = "Status",
    date_marker: str = "Datum",
    doctor_marker: str = "Arzt",
) -> list[MedicationRecord]:
    """Extract structured medication records from documents.

    Supports key-value block format (separated by blank lines or bullets) and table rows.
    """
    records: list[MedicationRecord] = []

    for sid in source_ids:
        text = texts.get(sid, "")
        lines = text.splitlines()
        current: dict[str, tuple[str, int]] = {}

        def _flush_current(curr_dict: dict[str, tuple[str, int]], sid_val: str) -> None:
            if medication_marker not in curr_dict:
                return
            med_name, m_line = curr_dict[medication_marker]
            if not med_name.strip():
                return
            ing_val, _ = curr_dict.get(ingredient_marker, ("", m_line))
            dos_val, _ = curr_dict.get(dosage_marker, ("", m_line))
            sch_val, _ = curr_dict.get(schedule_marker, ("", m_line))
            ind_val, _ = curr_dict.get(indication_marker, ("", m_line))
            st_val, _ = curr_dict.get(status_marker, ("laufend", m_line))
            dt_val, _ = curr_dict.get(date_marker, ("", m_line))
            dr_val, _ = curr_dict.get(doctor_marker, ("", m_line))

            quote_parts = [f"{k}: {v[0]}" for k, v in curr_dict.items()]
            quote = " · ".join(quote_parts)

            dos_num, dos_unit = _parse_dosage(dos_val)
            records.append(
                MedicationRecord(
                    name=med_name.strip(),
                    active_ingredient=ing_val.strip() if ing_val.strip() else None,
                    dosage=dos_val.strip(),
                    dosage_numeric=dos_num,
                    dosage_unit=dos_unit,
                    schedule=sch_val.strip() if sch_val.strip() else "nach Bedarf",
                    indication=ind_val.strip() if ind_val.strip() else None,
                    status=st_val.strip().lower() if st_val.strip() else "laufend",
                    date=dt_val.strip() if dt_val.strip() else None,
                    doctor=dr_val.strip() if dr_val.strip() else None,
                    anchor=Anchor(source_id=sid_val, line=m_line),
                    quote=quote,
                )
            )

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                _flush_current(current, sid)
                current = {}
                continue

            # Check markdown/pipe table row
            if (
                stripped.startswith("|")
                and stripped.endswith("|")
                and not stripped.startswith("|---")
            ):
                parts = [p.strip() for p in stripped[1:-1].split("|")]
                is_header = any(
                    p.lower() in ("medikament", "name", "präparat") for p in parts
                )
                if len(parts) >= 3 and not is_header:
                    # Data row
                    med = parts[0]
                    ing = parts[1] if len(parts) > 1 else ""
                    dos = parts[2] if len(parts) > 2 else ""
                    sch = parts[3] if len(parts) > 3 else ""
                    ind = parts[4] if len(parts) > 4 else ""
                    st = parts[5] if len(parts) > 5 else "laufend"
                    dt = parts[6] if len(parts) > 6 else ""
                    dr = parts[7] if len(parts) > 7 else ""
                    dos_num, dos_unit = _parse_dosage(dos)
                    records.append(
                        MedicationRecord(
                            name=med,
                            active_ingredient=ing if ing else None,
                            dosage=dos,
                            dosage_numeric=dos_num,
                            dosage_unit=dos_unit,
                            schedule=sch if sch else "nach Bedarf",
                            indication=ind if ind else None,
                            status=st.lower() if st else "laufend",
                            date=dt if dt else None,
                            doctor=dr if dr else None,
                            anchor=Anchor(source_id=sid, line=line_num),
                            quote=stripped,
                        )
                    )
                    continue

            # Check key-value marker
            matched = False
            for marker in (
                medication_marker,
                ingredient_marker,
                dosage_marker,
                schedule_marker,
                indication_marker,
                status_marker,
                date_marker,
                doctor_marker,
                "Dosis",
                "Stärke",
                "Einnahmezeit",
                "Tageszeit",
                "Wirkung",
                "Grund",
                "Präparat",
            ):
                pattern = re.compile(
                    rf"^(?:[-*•]\s*)?{re.escape(marker)}\s*:\s*(?P<val>\S.*?)\s*$",
                    re.IGNORECASE,
                )
                m = pattern.match(stripped)
                if m:
                    # Map aliases to canonical marker
                    canon = marker
                    if marker in ("Dosis", "Stärke"):
                        canon = dosage_marker
                    elif marker in ("Einnahmezeit", "Tageszeit"):
                        canon = schedule_marker
                    elif marker in ("Wirkung", "Grund"):
                        canon = indication_marker
                    elif marker == "Präparat":
                        canon = medication_marker

                    current[canon] = (m.group("val").strip(), line_num)
                    matched = True
                    break

            if not matched and stripped.startswith(("-", "*", "•")) and ":" in stripped:
                # Fallback colon inside bullet
                parts = stripped.lstrip("-*• ").split(":", 1)
                k = parts[0].strip()
                v = parts[1].strip()
                current[k] = (v, line_num)

        _flush_current(current, sid)

    return records


def reconcile_medications(
    records: list[MedicationRecord],
    *,
    user_corrections: dict[str, Any] | None = None,
) -> MedicationReconciliationSummary:
    """Reconcile extracted medications, detect conflicts, and apply user corrections."""
    corrections = user_corrections or {}

    # Group by normalized medication name
    groups: dict[str, list[MedicationRecord]] = {}
    for r in records:
        norm = _normalize_med_name(r.name)
        groups.setdefault(norm, []).append(r)

    consolidated_list: list[ConsolidatedMedication] = []
    all_conflicts: list[MedicationConflict] = []
    unresolved_conflicts: list[MedicationConflict] = []

    for norm_name, recs in groups.items():
        base = recs[0]
        med_display_name = base.name
        ingredient = next((r.active_ingredient for r in recs if r.active_ingredient), None)
        indication = next((r.indication for r in recs if r.indication), None)

        # Check user correction for this medication (by exact name or normalized name)
        user_res: dict[str, Any] | None = None
        for k, v in corrections.items():
            if _normalize_med_name(k) == norm_name:
                if isinstance(v, dict):
                    user_res = v
                break

        # Check dosage conflicts
        distinct_dosages = {
            (r.dosage_numeric, r.dosage_unit)
            if r.dosage_numeric is not None
            else r.dosage.casefold()
            for r in recs
            if r.dosage
        }

        # Check schedule conflicts
        distinct_schedules = {r.schedule.casefold() for r in recs if r.schedule}

        # Check status conflicts
        distinct_statuses = {r.status.casefold() for r in recs if r.status}

        conflict: MedicationConflict | None = None

        if len(distinct_dosages) > 1:
            # Conflicting dosages detected
            desc_parts = [
                f"{r.doctor or r.anchor.source_id} ({r.date or 'kein Datum'}): {r.dosage}"
                for r in recs
            ]
            desc = (
                f"Widersprüchliche Dosierungsangaben für '{med_display_name}': "
                + "; ".join(desc_parts)
            )
            is_resolved = False
            res_note = ""
            resolved_by = ""
            if user_res and "dosage" in user_res:
                is_resolved = True
                res_note = str(user_res.get("confirmed_by", "Vom Nutzer/Arzt bestätigt"))
                resolved_by = "user_confirmed"

            conflict = MedicationConflict(
                kind="conflicting_dosages",
                medication_name=med_display_name,
                description=desc,
                competing_records=tuple(recs),
                resolved=is_resolved,
                resolution_note=res_note,
                resolved_by=resolved_by,
            )
        elif len(distinct_schedules) > 1:
            # Conflicting schedules
            desc_parts = [
                f"{r.doctor or r.anchor.source_id}: {r.schedule}"
                for r in recs
            ]
            desc = (
                f"Abweichende Einnahmeschemata für '{med_display_name}': "
                + "; ".join(desc_parts)
            )
            is_resolved = False
            res_note = ""
            resolved_by = ""
            if user_res and ("schedule" in user_res or "confirmed_by" in user_res):
                is_resolved = True
                res_note = str(user_res.get("confirmed_by", "Einnahmezeit vom Nutzer bestätigt"))
                resolved_by = "user_confirmed"

            conflict = MedicationConflict(
                kind="conflicting_schedules",
                medication_name=med_display_name,
                description=desc,
                competing_records=tuple(recs),
                resolved=is_resolved,
                resolution_note=res_note,
                resolved_by=resolved_by,
            )
        elif len(distinct_statuses) > 1:
            desc = (
                f"Widersprüchlicher Status für '{med_display_name}': "
                f"{', '.join(distinct_statuses)}"
            )
            is_resolved = False
            res_note = ""
            resolved_by = ""
            if user_res and "status" in user_res:
                is_resolved = True
                res_note = str(user_res.get("confirmed_by", "Status bestätigt"))
                resolved_by = "user_confirmed"

            conflict = MedicationConflict(
                kind="conflicting_status",
                medication_name=med_display_name,
                description=desc,
                competing_records=tuple(recs),
                resolved=is_resolved,
                resolution_note=res_note,
                resolved_by=resolved_by,
            )

        if conflict:
            all_conflicts.append(conflict)
            if not conflict.resolved:
                unresolved_conflicts.append(conflict)

        # Decide chosen dosage and schedule
        if user_res and "dosage" in user_res:
            chosen_dosage = str(user_res["dosage"])
            chosen_dos_num, chosen_dos_unit = _parse_dosage(chosen_dosage)
        else:
            chosen_dosage = base.dosage
            chosen_dos_num = base.dosage_numeric
            chosen_dos_unit = base.dosage_unit

        if user_res and "schedule" in user_res:
            chosen_schedule = str(user_res["schedule"])
        else:
            chosen_schedule = base.schedule

        if user_res and "status" in user_res:
            chosen_status = str(user_res["status"])
        else:
            chosen_status = base.status

        sources_summary = ", ".join(
            dict.fromkeys(
                f"{r.doctor or r.anchor.source_id} (Z. {r.anchor.line})" for r in recs
            )
        )

        consolidated_list.append(
            ConsolidatedMedication(
                name=med_display_name,
                active_ingredient=ingredient,
                dosage=chosen_dosage,
                dosage_numeric=chosen_dos_num,
                dosage_unit=chosen_dos_unit,
                schedule=chosen_schedule,
                indication=indication,
                status=chosen_status,
                records=tuple(recs),
                conflict=conflict,
                resolution_note=(
                    conflict.resolution_note if conflict and conflict.resolved else None
                ),
                source_anchors=tuple(r.anchor for r in recs),
                sources_summary=sources_summary,
            )
        )

    # Check for duplicate active ingredients across different medications
    ing_map: dict[str, list[ConsolidatedMedication]] = {}
    for c in consolidated_list:
        norm_ing = _normalize_ingredient(c.active_ingredient)
        if norm_ing:
            ing_map.setdefault(norm_ing, []).append(c)

    duplicate_ingredient_count = 0
    for norm_ing, med_group in ing_map.items():
        if len(med_group) > 1:
            duplicate_ingredient_count += 1
            names = [m.name for m in med_group]
            dup_conflict = MedicationConflict(
                kind="duplicate_active_ingredient",
                medication_name=", ".join(names),
                description=(
                    f"Mehrfachverordnung des Wirkstoffs '{norm_ing}': "
                    f"Wird in {len(names)} verschiedenen Präparaten geführt ({', '.join(names)})."
                ),
                competing_records=tuple(r for m in med_group for r in m.records),
                resolved=True,  # Non-blocking alert / notification
                resolution_note="Wirkstoffüberschneidung erfasst",
                resolved_by="system_audit",
            )
            all_conflicts.append(dup_conflict)

    unique_sources = {r.anchor.source_id for r in records}
    resolved_count = sum(
        1 for c in all_conflicts if c.resolved and c.kind != "duplicate_active_ingredient"
    )

    return MedicationReconciliationSummary(
        consolidated=tuple(consolidated_list),
        conflicts=tuple(all_conflicts),
        unresolved_conflicts=tuple(unresolved_conflicts),
        total_medications=len(consolidated_list),
        total_sources=len(unique_sources),
        unresolved_conflict_count=len(unresolved_conflicts),
        resolved_conflict_count=resolved_count,
        duplicate_ingredient_count=duplicate_ingredient_count,
        has_blocking_conflicts=len(unresolved_conflicts) > 0,
    )


def _render_medication_markdown(
    summary: MedicationReconciliationSummary,
    title: str,
) -> str:
    """Render a consolidated medication plan in clean GitHub-flavored markdown."""
    lines: list[str] = [
        f"# {title}",
        "",
        "> [!IMPORTANT]",
        f"> **Medizinische Nichtautorität:** {summary.medical_disclaimer}",
        "",
        "## Konsolidierter Medikationsplan",
        "",
        "| Präparat | Wirkstoff | Dosis | Schema | Indikation | Status | Quellen | Bestätigt |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for m in summary.consolidated:
        ing = m.active_ingredient or "-"
        ind = m.indication or "-"
        conf_status = "Kein Konflikt"
        if m.conflict:
            if m.conflict.resolved:
                conf_status = f"Bestätigt ({m.conflict.resolution_note})"
            else:
                conf_status = f"**Widerspruch** ({m.conflict.description})"

        lines.append(
            f"| **{m.name}** | {ing} | {m.dosage} | {m.schedule} | "
            f"{ind} | {m.status} | {m.sources_summary} | {conf_status} |"
        )

    lines.append("")
    if summary.conflicts:
        lines.append("## Befundabgleich & Konfliktprotokoll")
        lines.append("")
        for c in summary.conflicts:
            icon = "✅" if c.resolved else "⚠️"
            lines.append(f"### {icon} {c.kind.replace('_', ' ').title()}: {c.medication_name}")
            lines.append(f"- **Beschreibung:** {c.description}")
            if c.resolved:
                lines.append(f"- **Status:** Gelöst / Bestätigt ({c.resolution_note})")
            else:
                lines.append("- **Status:** Ungeklärt — manuelle fachliche Freigabe erforderlich")
            lines.append("- **Beteiligte Quellen:**")
            for r in c.competing_records:
                loc = f"{r.doctor or r.anchor.source_id} (Z. {r.anchor.line})"
                lines.append(f"  - {loc}: `{r.quote}`")
            lines.append("")

    lines.append("---")
    lines.append(
        f"*Erstellt mit NemoFold Medikations-Reconciliation · Gesamt: "
        f"{summary.total_medications} Präparate aus {summary.total_sources} Quelle(n).*"
    )
    lines.append("")
    return "\n".join(lines)


def execute_medication_reconcile(
    job: Any,
    data: ChronicleInput,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    """Execute medication reconciliation across medical reports.

    Fail-closed policy:
    - If require_unambiguous_dosages is True and unresolved conflicts occur, halts with
      WorkflowBlocked and requests user input rather than inventing medical facts.
    - If fewer medications found than min_medications, halts with WorkflowBlocked.
    - If extracted medication records contain missing/empty names, halts with WorkflowBlocked.
    """
    records = extract_medications_from_texts(
        data.source_ids,
        data.texts,
        medication_marker=str(job.parameters.get("medication_marker", "Medikament")),
        ingredient_marker=str(job.parameters.get("ingredient_marker", "Wirkstoff")),
        dosage_marker=str(job.parameters.get("dosage_marker", "Dosierung")),
        schedule_marker=str(job.parameters.get("schedule_marker", "Einnahme")),
        indication_marker=str(job.parameters.get("indication_marker", "Indikation")),
        status_marker=str(job.parameters.get("status_marker", "Status")),
        date_marker=str(job.parameters.get("date_marker", "Datum")),
        doctor_marker=str(job.parameters.get("doctor_marker", "Arzt")),
    )

    output = Path(job.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    # 1. Floor check: min_medications
    min_meds = int(job.parameters.get("min_medications", 1))
    if len(records) < min_meds:
        question = Question(
            field="medications",
            prompt=(
                f"Zu wenige Medikamenteneinträge gefunden ({len(records)} < {min_meds}). "
                "Bitte stellen Sie Dokumente mit Medikationsangaben bereit."
            ),
            why=(
                "Die Medikations-Konsolidierung verlangt mindestens "
                "die deklarierte Anzahl an Medikamenten."
            ),
            kind="text",
        )
        asked = needs_input_payload((question,), workflow=job.workflow)
        needs_art = write_text_artifact(
            output / f"{run_id}.needs-user-input.json",
            json.dumps(asked, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "needs-user-input",
        )
        raise WorkflowBlocked(
            (f"insufficient_medications:{len(records)}<{min_meds}",),
            actions=(f"analyzed {len(data.source_ids)} source(s)", "medications_insufficient"),
            artifacts=(needs_art,),
            coverage=_coverage(data, set()),
            metadata={
                "medication_count": len(records),
                "target_min": min_meds,
                "needs_user_input": True,
            },
        )

    # 2. Check for missing required fields (e.g. empty name)
    for r in records:
        if not r.name or not r.dosage:
            question = Question(
                field="medication_schema",
                prompt=(
                    f"Unvollständiger Medikationsdatensatz in Quelle '{r.anchor.source_id}' "
                    f"Zeile {r.anchor.line}."
                ),
                why=(
                    "Jeder Medikationsdatensatz erfordert mindestens "
                    "Medikamentenname und Dosierung."
                ),
                kind="text",
            )
            asked = needs_input_payload((question,), workflow=job.workflow)
            needs_art = write_text_artifact(
                output / f"{run_id}.needs-user-input.json",
                json.dumps(asked, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                "needs-user-input",
            )
            raise WorkflowBlocked(
                ("missing_required_medication_field",),
                actions=(f"analyzed {len(data.source_ids)} source(s)", "missing_fields_blocked"),
                artifacts=(needs_art,),
                coverage=_coverage(data, set()),
                metadata={
                    "source_id": r.anchor.source_id,
                    "line": r.anchor.line,
                    "needs_user_input": True,
                },
            )

    # 3. Reconcile
    user_corrections = job.parameters.get("user_corrections")
    summary = reconcile_medications(records, user_corrections=user_corrections)

    # 4. Fail-closed ambiguity/conflict gate
    require_unambiguous = bool(job.parameters.get("require_unambiguous_dosages", True))
    if require_unambiguous and summary.unresolved_conflicts:
        questions: list[Question] = []
        for conf in summary.unresolved_conflicts:
            norm = _normalize_med_name(conf.medication_name)
            questions.append(
                Question(
                    field=f"medication_conflict_{norm}",
                    prompt=(
                        f"Widersprüchliche Angaben für '{conf.medication_name}': "
                        f"{conf.description}. "
                        "Bitte geben Sie die ärztlich verordnete Dosierung und Einnahmezeit an."
                    ),
                    why=(
                        "NemoFold besitzt keine medizinische Entscheidungskompetenz (§ 29 MBO-Ä). "
                        "Widersprüchliche Dosierungen dürfen nicht automatisch entschieden werden."
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
            (f"conflicting_dosages:{summary.unresolved_conflict_count}",),
            actions=(f"analyzed {len(data.source_ids)} source(s)", "conflicting_dosages_blocked"),
            artifacts=(needs_art,),
            coverage=_coverage(data, set()),
            metadata={
                "unresolved_conflicts": summary.unresolved_conflict_count,
                "needs_user_input": True,
                "outcome_note": asked["outcome_note"],
            },
        )

    # 5. Build claims
    claims: list[Claim] = []
    cited_sources: set[str] = set()

    for med in summary.consolidated:
        locators: list[EvidenceLocator] = []
        for r in med.records:
            cited_sources.add(r.anchor.source_id)
            locators.append(
                EvidenceLocator(
                    source_id=r.anchor.source_id,
                    quote=r.quote,
                    section=f"line {r.anchor.line}",
                )
            )
        res_text = f" (ärztlich bestätigt: {med.resolution_note})" if med.resolution_note else ""
        stmt = (
            f"Medikament '{med.name}': Dosierung {med.dosage}, Einnahme {med.schedule}"
            f"{res_text}, belegt in {len(med.records)} Quelle(n)."
        )
        claims.append(Claim(statement=stmt, evidence=tuple(locators)))

    coverage = _coverage(data, cited_sources)

    # 6. JSON reconciliation payload
    title = str(job.parameters.get("title", "Konsolidierter Medikationsplan"))
    payload = {
        "schema": MEDICATION_RECONCILIATION_SCHEMA,
        "title": title,
        "medical_non_authority_notice": summary.medical_disclaimer,
        "total_medications": summary.total_medications,
        "total_sources": summary.total_sources,
        "unresolved_conflicts": summary.unresolved_conflict_count,
        "resolved_conflicts": summary.resolved_conflict_count,
        "duplicate_active_ingredients": summary.duplicate_ingredient_count,
        "medications": [
            {
                "name": m.name,
                "active_ingredient": m.active_ingredient,
                "dosage": m.dosage,
                "dosage_numeric": m.dosage_numeric,
                "dosage_unit": m.dosage_unit,
                "schedule": m.schedule,
                "indication": m.indication,
                "status": m.status,
                "sources": [
                    {
                        "source_id": r.anchor.source_id,
                        "line": r.anchor.line,
                        "quote": r.quote,
                        "doctor": r.doctor,
                        "date": r.date,
                    }
                    for r in m.records
                ],
                "conflict": {
                    "kind": m.conflict.kind,
                    "description": m.conflict.description,
                    "resolved": m.conflict.resolved,
                    "resolution_note": m.conflict.resolution_note,
                }
                if m.conflict
                else None,
            }
            for m in summary.consolidated
        ],
        "conflicts": [
            {
                "kind": c.kind,
                "medication_name": c.medication_name,
                "description": c.description,
                "resolved": c.resolved,
                "resolution_note": c.resolution_note,
                "resolved_by": c.resolved_by,
            }
            for c in summary.conflicts
        ],
    }

    json_art = _json_artifact(
        output, f"{run_id}.medication-reconcile.json", payload, "medication-reconciliation"
    )

    # 7. Render markdown and report formats
    md_content = _render_medication_markdown(summary, title)
    md_art = write_text_artifact(
        output / f"{run_id}.medication-reconcile.md", md_content, "markdown"
    )

    report_formats = tuple(job.parameters.get("formats", ["md"]))
    extra_formats = tuple(f for f in report_formats if f not in ("md", "markdown", "json"))
    rendered_arts: list[ArtifactRecord] = []
    if extra_formats:
        doc = ReportDocument(
            title=title,
            claims=tuple(claims),
            coverage=coverage,
            scope_notice=summary.medical_disclaimer,
        )
        rendered_arts = list(
            render_report_formats(
                doc,
                output,
                basename=f"{run_id}_medication_report",
                formats=extra_formats,
            )
        )

    artifacts = (json_art, md_art, *rendered_arts)
    actions = (
        f"consolidated {summary.total_medications} medication(s) from {len(records)} record(s)",
        f"resolved {summary.resolved_conflict_count} conflict(s), "
        f"duplicate ingredients {summary.duplicate_ingredient_count}",
    )
    metadata: dict[str, object] = {
        "total_medications": summary.total_medications,
        "total_sources": summary.total_sources,
        "resolved_conflicts": summary.resolved_conflict_count,
        "unresolved_conflicts": summary.unresolved_conflict_count,
        "duplicate_ingredients": summary.duplicate_ingredient_count,
        "application_domain": "medical_reports",
    }

    return actions, artifacts, coverage, metadata
