from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .acceptance_gates import (
    artifact_manifest_sha256,
    load_gate_register_template,
    verify_gate_evidence,
)
from .application import ExecutionConfig
from .artifacts import write_text_artifact
from .contracts import RunStatus
from .ledger import RunLedger
from .voyage_runs import VoyageRunResult, run_voyage


class G01AcceptanceError(RuntimeError):
    """Raised when the executable G01 acceptance chain does not meet its contract."""


@dataclass(frozen=True, slots=True)
class G01AcceptanceBundle:
    root: Path
    register_path: Path
    positive_dossier_path: Path
    missing_dossier_path: Path
    ambiguous_dossier_path: Path
    verification: dict[str, Any]


def run_g01_acceptance_bundle(
    output_root: str | Path,
) -> G01AcceptanceBundle:
    """Run the synthetic G01 positive and blocking paths and seal their evidence."""
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G01AcceptanceError(f"g01_evidence_root_not_empty:{root}")
    root.mkdir(parents=True, exist_ok=True)
    positive_inputs = _write_positive_fixture(root)
    missing_input = _write_missing_fixture(root)
    ambiguous_inputs = _write_ambiguous_fixture(root)
    config = ExecutionConfig(allowed_roots=(str(root),))

    positive = _run_positive_voyage(root, positive_inputs[0].parent, config)
    missing = _run_missing_voyage(root, missing_input.parent, config)
    ambiguous = _run_ambiguous_voyage(root, ambiguous_inputs[0].parent, config)

    positive_report, output_artifacts = _verify_positive_result(root, positive)
    missing_report, missing_artifacts = _verify_missing_result(root, missing)
    ambiguous_report, ambiguous_artifacts = _verify_ambiguous_result(root, ambiguous)

    handoff_path = root / "evidence" / "g01-handoff.json"
    handoff = positive.steps[-1].handoff
    if not isinstance(handoff, dict):
        raise G01AcceptanceError("g01_positive_handoff_missing")
    write_text_artifact(
        handoff_path,
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    input_artifacts = [
        _artifact_receipt(root, path)
        for path in (*positive_inputs, missing_input, *ambiguous_inputs)
    ]
    dossier_artifacts = (
        Path(positive.dossier_path),
        Path(positive.dossier_path).with_suffix(".md"),
        Path(missing.dossier_path),
        Path(missing.dossier_path).with_suffix(".md"),
        Path(ambiguous.dossier_path),
        Path(ambiguous.dossier_path).with_suffix(".md"),
    )
    output_receipts = [
        _artifact_receipt(root, path)
        for path in (
            *output_artifacts,
            *missing_artifacts,
            *ambiguous_artifacts,
            *dossier_artifacts,
        )
    ]
    receipt = {
        "run_id": positive.steps[-1].run_id,
        "input_sha256": artifact_manifest_sha256(input_artifacts),
        "output_sha256": artifact_manifest_sha256(output_receipts),
        "input_artifacts": input_artifacts,
        "output_artifacts": output_receipts,
        "handoff_receipts": [
            {
                "producer": "corpus_query",
                "consumer": "folder_digest",
                "artifact_path": _relative(root, handoff_path),
                "artifact_sha256": _sha256(handoff_path),
                "status": "verified",
                "evidence": (
                    "Das verifizierte Markdown-Suchergebnis mit Beleg und Zeilenanker "
                    "wurde hashgebunden an den Digest-Schritt übergeben."
                ),
            }
        ],
        "run_report": {
            "path": _relative(root, positive_report),
            "sha256": _sha256(positive_report),
            "status": "executed",
            "verified": True,
        },
        "result_checks": [
            {
                "name": "document_found_with_tax_id",
                "passed": True,
                "evidence": (
                    "Das Dokument mit Steuernummer wurde im Dokumentenbestand "
                    "eindeutig identifiziert und mit exakter Fundstelle belegt."
                ),
            },
            {
                "name": "exact_citation_and_line_locator",
                "passed": True,
                "evidence": (
                    "Fundstelle enthält den wörtlichen Nachweis der Steuernummer "
                    "mit Zeilenanker und ohne Halluzination."
                ),
            },
            {
                "name": "verified_artifact_handoff",
                "passed": True,
                "evidence": (
                    "Der Consumer-Schritt übernahm ausschließlich das verifizierte "
                    "Markdown-Suchergebnis ohne ungeprüfte Nebendateien."
                ),
            },
        ],
        "negative_path": {
            "case": "no_tax_id_found",
            "run_id": missing.steps[0].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "evidence": (
                "Kein Dokument mit Steuernummer vorhanden; die Kette stoppte vor "
                "dem Handoff und erzeugte eine strukturierte Rückfrage."
            ),
            "run_report": {
                "path": _relative(root, missing_report),
                "sha256": _sha256(missing_report),
            },
        },
        "additional_negative_paths": [
            {
                "case": "ambiguous_tax_id_matches",
                "run_id": ambiguous.steps[0].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "evidence": (
                    "Mehrere widersprüchliche Steuernummern gefunden; die Kette stoppte "
                    "vor dem Handoff und erzeugte eine Dokumentenauswahl-Rückfrage."
                ),
                "run_report": {
                    "path": _relative(root, ambiguous_report),
                    "sha256": _sha256(ambiguous_report),
                },
            }
        ],
    }

    register = load_gate_register_template()
    gate = next(item for item in register["gates"] if item["gate_id"] == "G01")
    gate["status"] = "partial"
    gate["evidence"] = {
        "test_nodes": [],
        "run_receipts": [receipt],
    }
    verification = verify_gate_evidence(register, root)
    register_path = root / "gate-register.g01.json"
    write_text_artifact(
        register_path,
        json.dumps(register, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )
    return G01AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(positive.dossier_path),
        missing_dossier_path=Path(missing.dossier_path),
        ambiguous_dossier_path=Path(ambiguous.dossier_path),
        verification=verification,
    )


def _write_positive_fixture(root: Path) -> tuple[Path, Path, Path]:
    reports = root / "positive" / "inputs" / "personal-records"
    reports.mkdir(parents=True, exist_ok=True)
    steuerbescheid = reports / "01-steuerbescheid-2025.txt"
    steuerbescheid.write_text(
        "Finanzamt Berlin-Mitte\n"
        "Bescheid für 2025 über Einkommensteuer\n"
        "Name der steuerpflichtigen Person: Alex Beispiel\n"
        "Die Steuernummer für diesen Bescheid lautet 12/345/67890 beim Finanzamt.\n"
        "Festgesetzte Steuer beträgt null Euro.\n"
        "Erstattungsbetrag für das Steuerjahr: 350 Euro.\n",
        encoding="utf-8",
    )
    versicherung = reports / "02-versicherungsnachweis.txt"
    versicherung.write_text(
        "Muster-Krankenkasse\n"
        "Mitgliedsbescheinigung\n"
        "Name: Alex Beispiel\n"
        "Versichertennummer: X123456789\n"
        "Versicherungsstatus: Pflichtversichert.\n",
        encoding="utf-8",
    )
    kontoauszug = reports / "03-kontoauszug.txt"
    kontoauszug.write_text(
        "Musterbank Girokonto\n"
        "Kontoauszug Monat Januar 2026\n"
        "Kontoinhaber: Alex Beispiel\n"
        "IBAN: DE02100100100123456789\n"
        "Endsaldo: 1.450,00 Euro.\n",
        encoding="utf-8",
    )
    return steuerbescheid, versicherung, kontoauszug


def _write_missing_fixture(root: Path) -> Path:
    reports = root / "missing-negative" / "inputs" / "personal-records"
    reports.mkdir(parents=True, exist_ok=True)
    versicherung = reports / "01-versicherungsnachweis.txt"
    versicherung.write_text(
        "Muster-Krankenkasse\n"
        "Mitgliedsbescheinigung\n"
        "Name: Alex Beispiel\n"
        "Versichertennummer: X123456789\n"
        "Versicherungsstatus: Pflichtversichert.\n",
        encoding="utf-8",
    )
    return versicherung


def _write_ambiguous_fixture(root: Path) -> tuple[Path, Path]:
    reports = root / "ambiguous-negative" / "inputs" / "personal-records"
    reports.mkdir(parents=True, exist_ok=True)
    bescheid_1 = reports / "01-steuerbescheid-2025.txt"
    bescheid_1.write_text(
        "Finanzamt Berlin-Mitte\n"
        "Bescheid für 2025 über Einkommensteuer\n"
        "Name der steuerpflichtigen Person: Alex Beispiel\n"
        "Die Steuernummer für diesen Bescheid lautet 12/345/67890 beim Finanzamt.\n"
        "Festgesetzte Steuer beträgt null Euro.\n",
        encoding="utf-8",
    )
    bescheid_2 = reports / "02-steuerbescheid-2024.txt"
    bescheid_2.write_text(
        "Finanzamt München-Nord\n"
        "Bescheid für 2024 über Einkommensteuer\n"
        "Name der steuerpflichtigen Person: Alex Beispiel\n"
        "Die Steuernummer für diesen Bescheid lautet 98/765/43210 beim Finanzamt.\n"
        "Festgesetzte Steuer beträgt hundert Euro.\n",
        encoding="utf-8",
    )
    return bescheid_1, bescheid_2


def _run_positive_voyage(
    root: Path,
    records: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    case = _g01_case(
        records,
        root / "positive" / "out",
        voyage_id="voyage_g01_acceptance_positive",
        title="Steuernummer · fiktiver Steuerbescheid",
        min_matches=1,
        max_matches=1,
    )
    return run_voyage(
        case,
        config,
        run_id="g01_acceptance_positive",
        base_dir=root,
    )


def _run_missing_voyage(
    root: Path,
    records: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    case = _g01_case(
        records,
        root / "missing-negative" / "out",
        voyage_id="voyage_g01_acceptance_missing_tax_id",
        title="Steuernummer · kein Steuerbescheid gefunden",
        min_matches=1,
    )
    return run_voyage(
        case,
        config,
        run_id="g01_acceptance_missing_tax_id",
        base_dir=root,
    )


def _run_ambiguous_voyage(
    root: Path,
    records: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    case = _g01_case(
        records,
        root / "ambiguous-negative" / "out",
        voyage_id="voyage_g01_acceptance_ambiguous_tax_id",
        title="Steuernummer · mehrdeutige Steuernummern gefunden",
        min_matches=1,
        max_matches=1,
    )
    return run_voyage(
        case,
        config,
        run_id="g01_acceptance_ambiguous_tax_id",
        base_dir=root,
    )


def _g01_case(
    records: Path,
    output_root: Path,
    *,
    voyage_id: str,
    title: str,
    min_matches: int = 0,
    max_matches: int | None = None,
) -> dict[str, Any]:
    query_parameters: dict[str, Any] = {
        "terms": ["Steuernummer"],
        "formats": ["md"],
        "title": title,
    }
    if min_matches > 0:
        query_parameters["min_matches"] = min_matches
    if max_matches is not None:
        query_parameters["max_matches"] = max_matches

    return {
        "voyage_id": voyage_id,
        "name": title,
        "steps": [
            {
                "workflow": "corpus_query",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "corpus_query",
                    "input_roots": [str(records)],
                    "output_dir": str(output_root / "query"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": query_parameters,
                },
            },
            {
                "workflow": "folder_digest",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(records)],
                    "output_dir": str(output_root / "digest"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "summary_length": 3,
                        "digest_depth": "full",
                    },
                },
                "handoff": {
                    "format": "markdown",
                },
            },
        ],
    }


def _verify_positive_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "executed" or len(result.steps) != 2:
        raise G01AcceptanceError("g01_positive_voyage_not_executed")
    handoff = result.steps[-1].handoff or {}
    if handoff.get("status") != "verified":
        raise G01AcceptanceError("g01_positive_handoff_not_verified")
    if handoff.get("producer_workflow") != "corpus_query":
        raise G01AcceptanceError("g01_positive_producer_workflow_mismatch")
    if handoff.get("format") != "markdown":
        raise G01AcceptanceError("g01_positive_handoff_format_mismatch")

    producer_job = (
        root / "positive" / "out" / "query" / "jobs"
        / f"{result.steps[0].run_id}.json"
    )
    consumer_job = (
        root / "positive" / "out" / "digest" / "jobs"
        / f"{result.steps[-1].run_id}.json"
    )
    if not producer_job.is_file() or not consumer_job.is_file():
        raise G01AcceptanceError("g01_positive_job_snapshot_missing")

    producer_report_path = result.steps[0].ledger_path
    if producer_report_path is None:
        raise G01AcceptanceError("g01_positive_producer_report_missing")
    producer_report = RunLedger(Path(producer_report_path).parent).load(
        result.steps[0].run_id
    )

    query_json = next(
        (
            Path(item.path)
            for item in producer_report.artifacts
            if item.format == "corpus-query"
        ),
        None,
    )
    query_markdown = next(
        (
            Path(item.path)
            for item in producer_report.artifacts
            if item.format == "markdown"
        ),
        None,
    )
    if query_json is None or query_markdown is None:
        raise G01AcceptanceError("g01_positive_producer_artifacts_missing")

    query_data = json.loads(query_json.read_text(encoding="utf-8"))
    if query_data.get("match_count") != 1:
        raise G01AcceptanceError("g01_positive_match_count_mismatch")
    matches = query_data.get("matches", [])
    if not matches or "12/345/67890" not in matches[0].get("statement", ""):
        raise G01AcceptanceError("g01_positive_match_statement_mismatch")
    if not matches[0].get("anchors") or matches[0]["anchors"][0].get("line") != 4:
        raise G01AcceptanceError("g01_positive_match_anchor_mismatch")

    producer_snapshot = json.loads(producer_job.read_text(encoding="utf-8"))
    source_map = {
        s["source_id"]: s["path"]
        for s in producer_snapshot.get("job", {}).get("sources", [])
    }
    matched_source_id = matches[0]["anchors"][0]["source_id"]
    if not source_map.get(matched_source_id, "").endswith("01-steuerbescheid-2025.txt"):
        raise G01AcceptanceError("g01_positive_matched_source_mismatch")

    query_text = query_markdown.read_text(encoding="utf-8")
    if "12/345/67890" not in query_text or matched_source_id not in query_text:
        raise G01AcceptanceError("g01_positive_query_markdown_missing_citation")

    consumer_report_path = result.steps[-1].ledger_path
    if consumer_report_path is None:
        raise G01AcceptanceError("g01_positive_consumer_report_missing")
    consumer_report = RunLedger(Path(consumer_report_path).parent).load(
        result.steps[-1].run_id
    )
    if consumer_report.status is not RunStatus.EXECUTED:
        raise G01AcceptanceError("g01_positive_consumer_not_executed")
    if consumer_report.coverage is None or consumer_report.coverage.total_sources != 1:
        raise G01AcceptanceError("g01_positive_consumer_coverage_mismatch")

    digest_markdown = next(
        (
            Path(item.path)
            for item in consumer_report.artifacts
            if item.format == "folder-digest"
        ),
        None,
    )
    if digest_markdown is None or not digest_markdown.is_file():
        raise G01AcceptanceError("g01_positive_digest_artifact_missing")

    return Path(consumer_report_path), (
        query_json,
        query_markdown,
        digest_markdown,
        producer_job,
        consumer_job,
    )


def _verify_missing_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped" or len(result.steps) != 1:
        raise G01AcceptanceError("g01_missing_voyage_not_stopped")
    step = result.steps[0]
    if step.status != "blocked" or step.errors != ("no_matches_found:Steuernummer",):
        raise G01AcceptanceError("g01_missing_reason_mismatch")
    if step.ledger_path is None:
        raise G01AcceptanceError("g01_missing_run_report_missing")
    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    if report.status is not RunStatus.BLOCKED:
        raise G01AcceptanceError("g01_missing_report_status_not_blocked")
    if report.metadata.get("needs_user_input") is not True:
        raise G01AcceptanceError("g01_missing_metadata_needs_user_input_missing")

    needs_artifact = next(
        (Path(item.path) for item in report.artifacts if item.format == "needs-user-input"),
        None,
    )
    if needs_artifact is None or not needs_artifact.is_file():
        raise G01AcceptanceError("g01_missing_needs_input_artifact_missing")
    question_data = json.loads(needs_artifact.read_text(encoding="utf-8"))
    questions = question_data.get("questions", [])
    if not questions or questions[0].get("kind") != "search_term":
        raise G01AcceptanceError("g01_missing_question_kind_mismatch")

    if (root / "missing-negative" / "out" / "digest").exists():
        raise G01AcceptanceError("g01_missing_consumer_digest_started")

    return Path(step.ledger_path), (needs_artifact,)


def _verify_ambiguous_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped" or len(result.steps) != 1:
        raise G01AcceptanceError("g01_ambiguous_voyage_not_stopped")
    step = result.steps[0]
    if step.status != "blocked" or step.errors != ("ambiguous_matches:2>1",):
        raise G01AcceptanceError("g01_ambiguous_reason_mismatch")
    if step.ledger_path is None:
        raise G01AcceptanceError("g01_ambiguous_run_report_missing")
    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    if report.status is not RunStatus.BLOCKED:
        raise G01AcceptanceError("g01_ambiguous_report_status_not_blocked")
    if report.metadata.get("needs_user_input") is not True:
        raise G01AcceptanceError("g01_ambiguous_metadata_needs_user_input_missing")

    needs_artifact = next(
        (Path(item.path) for item in report.artifacts if item.format == "needs-user-input"),
        None,
    )
    if needs_artifact is None or not needs_artifact.is_file():
        raise G01AcceptanceError("g01_ambiguous_needs_input_artifact_missing")
    question_data = json.loads(needs_artifact.read_text(encoding="utf-8"))
    questions = question_data.get("questions", [])
    if not questions or questions[0].get("kind") != "document_selection":
        raise G01AcceptanceError("g01_ambiguous_question_kind_mismatch")

    if (root / "ambiguous-negative" / "out" / "digest").exists():
        raise G01AcceptanceError("g01_ambiguous_consumer_digest_started")

    return Path(step.ledger_path), (needs_artifact,)


def _artifact_receipt(root: Path, path: Path) -> dict[str, str]:
    return {"path": _relative(root, path), "sha256": _sha256(path)}


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise G01AcceptanceError(f"g01_evidence_path_outside_root:{path}") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
