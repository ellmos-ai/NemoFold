"""Design & Document QA for finished documents and publication packages (G13).

Validates finished documents (e.g. ASCII Lebenslauf UC01, Autismus-Arbeitsblatt
UC39, psychologisches Beratungsblatt UC40) for format integrity, substantive
completeness, absence of unreplaced template placeholders, and cryptographic
SHA-256 hash preservation. Assembles verified documents into sealed publication
packages with honest report-forge fallback/blocker reporting.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .artifacts import write_text_artifact
from .completeness import Question, needs_input_payload
from .contracts import ArtifactRecord, Coverage, WorkflowBlocked
from .document_compose import engine_status
from .evidence import compute_coverage
from .inventory import InventoryResult
from .job_io import JobEnvelope

PLACEHOLDER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\{\{[^}\n]+\}\}"),
    re.compile(r"\[PLATZHALTER[^\]\n]*\]", re.IGNORECASE),
    re.compile(r"<[A-Z0-9_ -]{3,}>"),
    re.compile(r"\b(TODO|TBD)\b"),
)

SUPPORTED_QA_FORMATS: frozenset[str] = frozenset(
    {"md", "markdown", "txt", "text", "json", "pdf", "docx"}
)


class DocumentQAError(ValueError):
    """Raised when Document QA encounters an unrecoverable contract violation."""


@dataclass(frozen=True, slots=True)
class QACheckItem:
    name: str
    passed: bool
    evidence: str


@dataclass(frozen=True, slots=True)
class QAResult:
    passed: bool
    document_path: str
    document_sha256: str
    detected_format: str
    version: str
    checks: tuple[QACheckItem, ...]
    unbound_fields: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def _detect_format(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in ("md", "markdown"):
        return "markdown"
    if suffix in ("txt", "text"):
        return "text"
    if suffix == "json":
        return "json"
    if suffix in ("pdf", "docx"):
        return suffix
    return suffix or "unknown"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def validate_document_qa(
    text: str,
    path: Path,
    *,
    expected_sha256: str | None = None,
    required_sections: tuple[str, ...] = (),
    disallow_unbound_fields: bool = True,
    min_words: int = 10,
    target_format: str = "markdown",
    version: str = "1.0",
) -> QAResult:
    """Run format, completeness, placeholder, and hash QA checks over a document."""
    checks: list[QACheckItem] = []
    errors: list[str] = []
    unbound_fields: list[str] = []

    # 1. Format check
    detected = _detect_format(path)
    format_ok = detected in ("markdown", "text", "json", "pdf", "docx")
    if target_format:
        norm_target = target_format.lower().lstrip(".")
        is_md = norm_target in ("md", "markdown") and detected == "markdown"
        is_txt = norm_target in ("txt", "text") and detected == "text"
        if is_md or is_txt:
            format_ok = True
        elif norm_target != detected:
            format_ok = False
    checks.append(
        QACheckItem(
            name="format_integrity",
            passed=format_ok,
            evidence=(
                f"Detected format '{detected}' matches target '{target_format}'."
                if format_ok
                else f"Format mismatch: detected '{detected}', expected '{target_format}'."
            ),
        )
    )
    if not format_ok:
        errors.append(f"document_format_mismatch:detected={detected}:expected={target_format}")

    # 2. Hash & Integrity Check
    actual_sha = _sha256_file(path)
    if expected_sha256 is not None and expected_sha256.strip():
        hash_ok = actual_sha.lower() == expected_sha256.strip().lower()
        checks.append(
            QACheckItem(
                name="hash_integrity",
                passed=hash_ok,
                evidence=(
                    f"Cryptographic hash verified: {actual_sha}."
                    if hash_ok
                    else (
                        f"Hash mismatch: actual {actual_sha} does not match expected "
                        f"{expected_sha256.strip()}."
                    )
                ),
            )
        )
        if not hash_ok:
            errors.append(
                f"source_document_hash_mismatch:actual={actual_sha}:expected={expected_sha256}"
            )
    else:
        checks.append(
            QACheckItem(
                name="hash_integrity",
                passed=True,
                evidence=f"Cryptographic SHA-256 calculated and anchored: {actual_sha}.",
            )
        )

    # 3. Completeness: minimum length / word count
    words = text.split()
    word_count = len(words)
    length_ok = word_count >= min_words
    checks.append(
        QACheckItem(
            name="content_completeness",
            passed=length_ok,
            evidence=(
                f"Document contains {word_count} words (minimum required: {min_words})."
                if length_ok
                else f"Document has only {word_count} words (minimum required: {min_words})."
            ),
        )
    )
    if not length_ok:
        errors.append(f"document_incomplete_too_short:words={word_count}:min={min_words}")

    # 4. Completeness: required sections / keywords
    missing_sections: list[str] = []
    text_lower = text.casefold()
    for section in required_sections:
        if section.casefold() not in text_lower:
            missing_sections.append(section)
    sections_ok = len(missing_sections) == 0
    checks.append(
        QACheckItem(
            name="required_sections_present",
            passed=sections_ok,
            evidence=(
                f"All {len(required_sections)} required sections/markers are present."
                if sections_ok
                else f"Missing required sections/markers: {', '.join(missing_sections)}."
            ),
        )
    )
    if not sections_ok:
        errors.append(
            f"document_incomplete:missing_required_sections:{','.join(missing_sections)}"
        )

    # 5. Placeholder & Unbound field detection
    if disallow_unbound_fields:
        for pattern in PLACEHOLDER_PATTERNS:
            for match in pattern.finditer(text):
                unbound_fields.append(match.group(0))
        placeholders_ok = len(unbound_fields) == 0
        checks.append(
            QACheckItem(
                name="unbound_fields_checked",
                passed=placeholders_ok,
                evidence=(
                    "No unreplaced placeholders or unbound template tokens found."
                    if placeholders_ok
                    else (
                        f"Found {len(unbound_fields)} unbound template token(s): "
                        f"{', '.join(unbound_fields[:5])}."
                    )
                ),
            )
        )
        if not placeholders_ok:
            errors.append(
                f"unbound_fields_in_document:count={len(unbound_fields)}:"
                f"tokens={','.join(unbound_fields[:3])}"
            )
    else:
        checks.append(
            QACheckItem(
                name="unbound_fields_checked",
                passed=True,
                evidence="Placeholder check disabled by policy.",
            )
        )

    all_passed = len(errors) == 0
    return QAResult(
        passed=all_passed,
        document_path=str(path),
        document_sha256=actual_sha,
        detected_format=detected,
        version=version,
        checks=tuple(checks),
        unbound_fields=tuple(unbound_fields),
        errors=tuple(errors),
    )


def build_publication_package(
    qa_result: QAResult,
    run_id: str,
    *,
    package_title: str = "Publikationspaket",
) -> tuple[dict[str, Any], str]:
    """Assemble a validated publication package payload and summary markdown."""
    status = engine_status()
    payload: dict[str, Any] = {
        "schema": "nemofold.publication-package.v1",
        "package_id": f"pkg_{run_id}",
        "package_title": package_title,
        "document_path": qa_result.document_path,
        "document_sha256": qa_result.document_sha256,
        "format": qa_result.detected_format,
        "version": qa_result.version,
        "qa_passed": qa_result.passed,
        "checks": [
            {
                "name": item.name,
                "passed": item.passed,
                "evidence": item.evidence,
            }
            for item in qa_result.checks
        ],
        "template_engine_status": status.as_metadata(),
        "fallback_applied": not status.available,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "boundary_note": (
            "NemoFold verifies format, completeness, and hash integrity before sealing "
            "the publication package. Original document and version are preserved."
        ),
    }

    status_badge = "VERIFIED" if qa_result.passed else "FAILED"
    engine_note = (
        "Report-Forge ist nicht installiert; ehrlicher Fallback auf Standalone-Publikationspaket."
        if not status.available
        else f"Report-Forge verfügbar ({status.version})."
    )

    rows: list[str] = []
    for item in qa_result.checks:
        symbol = "PASS" if item.passed else "FAIL"
        rows.append(f"| {item.name} | {symbol} | {item.evidence} |")
    checks_table = "\n".join(rows)

    md = (
        f"# {package_title}\n\n"
        f"- **Paket-ID:** `pkg_{run_id}`\n"
        f"- **Status:** `{status_badge}`\n"
        f"- **Dokument:** `{Path(qa_result.document_path).name}`\n"
        f"- **SHA-256:** `{qa_result.document_sha256}`\n"
        f"- **Format:** `{qa_result.detected_format}`\n"
        f"- **Version:** `{qa_result.version}`\n"
        f"- **Template-Engine:** `{engine_note}`\n\n"
        f"## Qualitaets- und Integritaetspruefung (QA)\n\n"
        f"| Pruefung | Status | Befund |\n"
        f"|---|---|---|\n"
        f"{checks_table}\n\n"
        f"## Publikations- und Druckhinweise\n\n"
        f"Das Dokument wurde qualitaetsgeprueft und ist publikationsbereit.\n"
        f"Originaldokument und Hash-Provenienz bleiben vollstaendig erhalten.\n"
    )

    return payload, md


def execute_document_qa(
    job: JobEnvelope,
    inventory: InventoryResult,
    *,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    """Execute Document QA workflow: format, completeness, placeholder, hash checks."""
    params = job.parameters
    doc_path_param = str(params.get("document_path", "")).strip()

    target_file: Path | None = None
    if doc_path_param:
        candidate = Path(doc_path_param)
        if candidate.is_file():
            target_file = candidate
        else:
            for root_str in job.input_roots:
                combined = Path(root_str) / doc_path_param
                if combined.is_file():
                    target_file = combined
                    break

    if target_file is None:
        target_format = str(params.get("target_format", "markdown")).strip().lower()
        candidates: list[Path] = []
        for record in inventory.records:
            p = Path(record.path)
            if not p.is_file():
                continue
            if p.parent.name == "ledger" or "ledger" in p.parts:
                continue
            if p.name.endswith(".run-report.json") or p.name.endswith(".ledger.json"):
                continue
            if p.name.endswith(".publication-package.json"):
                continue
            if p.suffix.lower() in (".md", ".txt", ".json", ".docx", ".pdf"):
                candidates.append(p)

        target_exts = {
            "markdown": (".md", ".markdown"),
            "text": (".txt", ".text"),
            "json": (".json",),
            "pdf": (".pdf",),
            "docx": (".docx",),
        }.get(target_format, (f".{target_format}",))

        matching = [c for c in candidates if c.suffix.lower() in target_exts]
        if matching:
            target_file = matching[0]
        elif candidates:
            md_txt = [
                c for c in candidates if c.suffix.lower() in (".md", ".markdown", ".txt")
            ]
            target_file = md_txt[0] if md_txt else candidates[0]

    if target_file is None or not target_file.is_file():
        raise ValueError("document_qa needs a target document; specify with document_path")

    try:
        text_content = target_file.read_text(encoding="utf-8")
    except Exception as exc:
        raise WorkflowBlocked(
            (f"document_empty_or_unreadable:{exc}",),
            actions=("document_qa_failed",),
            artifacts=(),
            coverage=compute_coverage(
                all_source_ids=(r.source_id for r in inventory.records),
                read_source_ids={},
                cited_source_ids=set(),
            ),
            metadata={"error": str(exc)},
        ) from exc

    expected_sha = params.get("expected_sha256")
    required_sec = tuple(str(s) for s in params.get("required_sections", []))
    disallow_unbound = bool(params.get("disallow_unbound_fields", True))
    min_words = int(params.get("min_words", 10))
    target_fmt = str(params.get("target_format", "markdown"))
    version = str(params.get("version", "1.0"))
    package_title = str(params.get("package_title", "Publikationspaket"))

    qa_result = validate_document_qa(
        text_content,
        target_file,
        expected_sha256=expected_sha,
        required_sections=required_sec,
        disallow_unbound_fields=disallow_unbound,
        min_words=min_words,
        target_format=target_fmt,
        version=version,
    )

    output_dir = Path(job.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    coverage = compute_coverage(
        all_source_ids=(r.source_id for r in inventory.records),
        read_source_ids={target_file.name: text_content[:500]},
        cited_source_ids={target_file.name},
    )

    if not qa_result.passed:
        # If unbound fields, provide a needs_user_input artifact
        artifacts: list[ArtifactRecord] = []
        if qa_result.unbound_fields:
            question = Question(
                field="unbound_fields",
                prompt=(
                    f"Im Dokument wurden {len(qa_result.unbound_fields)} unersetzte "
                    "Platzhalter gefunden. Bitte die Werte vor der Publikation ergaenzen."
                ),
                why="Publikation von Dokumenten mit ungebundenen Template-Tokens ist verboten.",
                kind="text",
            )
            needs_payload = needs_input_payload((question,), workflow=job.workflow)
            needs_path = output_dir / f"{run_id}.needs-user-input.json"
            artifacts.append(
                write_text_artifact(
                    needs_path,
                    json.dumps(needs_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    "needs-user-input",
                )
            )

        raise WorkflowBlocked(
            qa_result.errors,
            actions=("document_qa_evaluated", "document_qa_blocked"),
            artifacts=tuple(artifacts),
            coverage=coverage,
            metadata={
                "qa_passed": False,
                "errors": list(qa_result.errors),
                "unbound_fields": list(qa_result.unbound_fields),
                "checks": [
                    {"name": c.name, "passed": c.passed, "evidence": c.evidence}
                    for c in qa_result.checks
                ],
            },
        )

    # QA passed: build publication package
    pkg_payload, pkg_md = build_publication_package(
        qa_result, run_id, package_title=package_title
    )

    qa_json_path = output_dir / f"{run_id}.document-qa.json"
    qa_artifact = write_text_artifact(
        qa_json_path,
        json.dumps(
            {
                "schema": "nemofold.document-qa.v1",
                "document_path": qa_result.document_path,
                "document_sha256": qa_result.document_sha256,
                "format": qa_result.detected_format,
                "version": qa_result.version,
                "qa_passed": True,
                "checks": [
                    {"name": c.name, "passed": c.passed, "evidence": c.evidence}
                    for c in qa_result.checks
                ],
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        "document-qa",
    )

    pkg_json_path = output_dir / f"{run_id}.publication-package.json"
    pkg_json_artifact = write_text_artifact(
        pkg_json_path,
        json.dumps(pkg_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "publication-package",
    )

    pkg_md_path = output_dir / f"{run_id}.publication-package.md"
    pkg_md_artifact = write_text_artifact(
        pkg_md_path,
        pkg_md,
        "markdown",
    )

    return (
        (
            "document_qa_evaluated",
            "format_verified",
            "completeness_verified",
            "hash_anchored",
            "publication_package_sealed",
        ),
        (qa_artifact, pkg_json_artifact, pkg_md_artifact),
        coverage,
        {
            "qa_passed": True,
            "document_sha256": qa_result.document_sha256,
            "version": qa_result.version,
            "checks_count": len(qa_result.checks),
        },
    )
