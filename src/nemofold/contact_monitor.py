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
    r"(?i)\b(owner|manager|lead|contact|responsib\w*|zuständig\w*|ansprechpartner\w*|leitung)\b"
)


def _candidate_lines(text: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in text.splitlines() if EMAIL_FINDER.search(line))


def _name_from_line(line: str, email: str) -> str | None:
    match = NAME_BEFORE_EMAIL.search(line)
    if match:
        name = match.group("name").strip(" ,;:-")
        return name or None
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
        for line in _candidate_lines(text):
            for email in EMAIL_FINDER.findall(line):
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
                    {"email": email, "name": None, "responsibility": None, "evidence": []},
                )
                candidate["name"] = candidate["name"] or _name_from_line(line, email)
                if ROLE_WORDS.search(line):
                    candidate["responsibility"] = candidate["responsibility"] or line[:500]

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
            for field in ("name", "responsibility")
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
    markdown = ["# Contact and responsibility monitor", ""]
    if not ordered:
        markdown.extend(("No contact candidates were found in the readable approved sources.", ""))
    for item in ordered:
        markdown.extend(
            (
                f"## {item.get('name') or item['email']}",
                "",
                f"- Email: {item['email']}",
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
    read_ids = tuple(source_id for source_id, text in texts.items() if text)
    cited_ids = sorted(
        {
            evidence["source_id"]
            for item in ordered
            for evidence in item["evidence"]
        }
    )
    return (
        (json_record, markdown_record),
        read_ids,
        {
            "candidate_count": len(ordered),
            "new_contact_count": len(new),
            "changed_contact_count": len(changed),
            "missing_contact_count": len(missing),
            "automatic_deletion": False,
            "cited_source_ids": cited_ids,
        },
    )
