from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .artifacts import write_text_artifact
from .contracts import ArtifactRecord, SourceRecord

EMAIL_FINDER = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
NAME_BEFORE_EMAIL = re.compile(r"(?P<name>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s*<[^>]+>")
ROLE_WORDS = re.compile(
    r"(?i)\b(owner|manager|lead|contact|responsib\w*|zuständig\w*|ansprechpartner\w*|leitung|"
    r"fachbereich|fachgebiet|facharzt|fachärztin|praxis|labor)\b"
)
PHONE_FINDER = re.compile(
    r"(?i)(?:tel(?:efon)?|phone|fon|mobil|fax)[:.]?\s*([+\d\s/()\-]{6,30}\d)"
)
STANDALONE_PHONE = re.compile(
    r"(?:\+49|0049|0)[1-9][0-9\s/()\-]{5,20}[0-9]"
)
DOCTOR_WORDS = re.compile(
    r"(?i)\b(dr\.|prof\.|arzt|ärztin|facharzt|fachärztin|med\.|praxis|klinik|"
    r"radiolog\w*|nuklearmed\w*|internist\w*|kardiolog\w*|labor\w*|mvz)\b"
)
NAME_WITH_TITLE = re.compile(
    r"(?P<name>(?:Prof\.\s*)?Dr\.\s*(?:med\.\s*)?[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})"
)


def _clean_phone(raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw).strip(" ,;:-.")
    return cleaned


def _extract_phone_from_lines(lines: list[str]) -> str | None:
    for line in lines:
        match = PHONE_FINDER.search(line)
        if match:
            return _clean_phone(match.group(1))
        match2 = STANDALONE_PHONE.search(line)
        if match2:
            return _clean_phone(match2.group(0))
    return None


def _candidate_lines(text: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in text.splitlines() if EMAIL_FINDER.search(line))


def _name_from_line(line: str, email: str) -> str | None:
    match = NAME_BEFORE_EMAIL.search(line)
    if match:
        name = match.group("name").strip(" ,;:-")
        return name or None
    title_match = NAME_WITH_TITLE.search(line)
    if title_match:
        return title_match.group("name").strip(" ,;:-")
    prefix = line[: line.casefold().find(email.casefold())].strip(" ,;:<>()-")
    if prefix and len(prefix) <= 80 and "@" not in prefix and ROLE_WORDS.search(prefix) is None:
        return prefix
    return None


def build_contact_monitor(
    records: tuple[SourceRecord, ...],
    texts: dict[str, str],
    output_dir: str | Path,
    *,
    run_id: str,
    since_run_id: str | None,
) -> tuple[tuple[ArtifactRecord, ...], tuple[str, ...], dict[str, object]]:
    labels = {record.source_id: record.display_name for record in records}
    candidates: dict[str, dict[str, Any]] = {}
    evidence_by_email: dict[str, list[dict[str, str]]] = defaultdict(list)

    for source_id, text in texts.items():
        all_lines = text.splitlines()
        for i, raw_line in enumerate(all_lines):
            line = raw_line.strip()
            emails = EMAIL_FINDER.findall(line)
            if not emails:
                continue

            window = [
                all_lines[j].strip()
                for j in range(max(0, i - 3), min(len(all_lines), i + 4))
                if all_lines[j].strip()
            ]
            phone = _extract_phone_from_lines([line, *window])
            is_doctor = any(DOCTOR_WORDS.search(w) for w in window) or bool(
                DOCTOR_WORDS.search(line)
            )

            for email in emails:
                key = email.casefold()
                evidence = {
                    "source_id": source_id,
                    "display_name": labels.get(source_id, source_id),
                    "quote": line[:500],
                }
                if evidence not in evidence_by_email[key]:
                    evidence_by_email[key].append(evidence)

                candidate = candidates.setdefault(
                    key,
                    {
                        "email": email,
                        "name": None,
                        "phone": None,
                        "contact_class": "contact",
                        "responsibility": None,
                        "evidence": [],
                    },
                )
                if not candidate["name"]:
                    candidate["name"] = _name_from_line(line, email)
                    if not candidate["name"]:
                        for w in window:
                            m = NAME_WITH_TITLE.search(w)
                            if m:
                                candidate["name"] = m.group("name").strip(" ,;:-")
                                break

                if phone and not candidate["phone"]:
                    candidate["phone"] = phone

                if is_doctor or (candidate["name"] and DOCTOR_WORDS.search(candidate["name"])):
                    candidate["contact_class"] = "doctor"

                if not candidate["responsibility"]:
                    if ROLE_WORDS.search(line):
                        candidate["responsibility"] = line[:500]
                    else:
                        for w in window:
                            if ROLE_WORDS.search(w) and "@" not in w:
                                candidate["responsibility"] = w[:500]
                                break

    for email, evidence_list in evidence_by_email.items():
        candidates[email]["evidence"] = evidence_list
    ordered = [candidates[key] for key in sorted(candidates)]
    current_by_email = {str(item["email"]).casefold(): item for item in ordered}
    prior_by_email: dict[str, dict[str, Any]] = {}
    if since_run_id is not None:
        prior_path = Path(output_dir) / "contacts" / f"{since_run_id}.json"
        try:
            prior = json.loads(prior_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("contact since_run_id snapshot is unavailable") from exc
        if not isinstance(prior, dict) or prior.get("schema") != "nemofold.contacts.v1":
            raise ValueError("contact since_run_id snapshot is invalid")
        prior_candidates = prior.get("candidates")
        if not isinstance(prior_candidates, list):
            raise ValueError("contact since_run_id candidates are invalid")
        prior_by_email = {
            str(item.get("email", "")).casefold(): item
            for item in prior_candidates
            if isinstance(item, dict) and item.get("email")
        }

    new = sorted(set(current_by_email) - set(prior_by_email))
    missing = sorted(set(prior_by_email) - set(current_by_email))
    changed = sorted(
        email
        for email in set(current_by_email) & set(prior_by_email)
        if any(
            current_by_email[email].get(field) != prior_by_email[email].get(field)
            for field in ("name", "responsibility", "phone", "contact_class")
        )
    )
    stable = sorted(set(current_by_email) & set(prior_by_email) - set(changed))
    payload = {
        "schema": "nemofold.contacts.v1",
        "run_id": run_id,
        "since_run_id": since_run_id,
        "candidates": ordered,
        "changes": {
            "new": new,
            "changed": changed,
            "stable": stable,
            "missing_from_current_sources": missing,
        },
        "automatic_deletion": False,
    }
    root = Path(output_dir) / "contacts"
    json_record = write_text_artifact(
        root / f"{run_id}.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        "contact-snapshot",
    )

    markdown = [
        "# Contact and responsibility monitor",
        "",
        "## Übersicht hinterlegte Ärzte- und Ansprechpartnerkontakte",
        "",
        "| Name | Klasse / Fachbereich | E-Mail | Telefon |",
        "|---|---|---|---|",
    ]
    if not ordered:
        markdown.append("| _(Keine Kontakte gefunden)_ | - | - | - |")
    else:
        for item in ordered:
            name = item.get("name") or item["email"]
            c_class = item.get("contact_class") or "contact"
            resp = item.get("responsibility")
            class_str = f"{c_class} ({resp})" if resp else c_class
            email = item["email"]
            phone = item.get("phone") or "nicht hinterlegt"
            markdown.append(f"| {name} | {class_str} | {email} | {phone} |")

    markdown.append("")
    for item in ordered:
        markdown.extend(
            (
                f"### {item.get('name') or item['email']}",
                "",
                f"- Email: {item['email']}",
                f"- Phone: {item.get('phone') or 'not established'}",
                f"- Class: {item.get('contact_class') or 'contact'}",
                f"- Responsibility: {item.get('responsibility') or 'not established'}",
                "- Evidence:",
            )
        )
        for evidence in item["evidence"]:
            markdown.append(
                f"  - `{evidence['display_name']}` (`{evidence['source_id']}`): "
                f"“{evidence['quote']}”"
            )
        markdown.append("")
    if missing:
        markdown.extend(
            (
                "## Review candidates no longer present in current sources",
                "",
                *(f"- {email} — retained for review; never auto-deleted" for email in missing),
                "",
            )
        )
    markdown_record = write_text_artifact(
        root / f"{run_id}.md", "\n".join(markdown), "contact-report"
    )

    book_lines = [
        "# NemoFold Contact Book",
        f"# Run ID: {run_id}",
        "",
    ]
    for item in ordered:
        c_name = item.get("name") or item["email"]
        c_class = item.get("contact_class") or "contact"
        c_email = item.get("email") or ""
        c_phone = item.get("phone") or ""
        c_note = item.get("responsibility") or ""
        parts = [
            f"name: {c_name}",
            f"class: {c_class}",
            f"email: {c_email}",
        ]
        if c_phone:
            parts.append(f"phone: {c_phone}")
        if c_note:
            parts.append(f"note: {c_note}")
        book_lines.append(" · ".join(parts))

    book_record = write_text_artifact(
        root / f"{run_id}.txt", "\n".join(book_lines) + "\n", "contact-book"
    )

    read_ids = tuple(source_id for source_id, text in texts.items() if text)
    cited_ids = sorted(
        {
            evidence["source_id"]
            for item in ordered
            for evidence in item["evidence"]
        }
    )
    return (
        (json_record, markdown_record, book_record),
        read_ids,
        {
            "candidate_count": len(ordered),
            "doctor_count": sum(1 for item in ordered if item.get("contact_class") == "doctor"),
            "with_phone_count": sum(1 for item in ordered if item.get("phone")),
            "new_contact_count": len(new),
            "changed_contact_count": len(changed),
            "missing_contact_count": len(missing),
            "automatic_deletion": False,
            "cited_source_ids": cited_ids,
        },
    )
