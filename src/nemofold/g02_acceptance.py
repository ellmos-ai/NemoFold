from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .acceptance_gates import (
    artifact_manifest_sha256,
    load_gate_register,
    verify_gate_evidence,
)
from .application import ExecutionConfig
from .artifacts import write_text_artifact
from .ledger import RunLedger
from .report_studio import _render_pdf
from .voyage_runs import VoyageRunResult, run_voyage
from .voyages import VoyageStore


class G02AcceptanceError(RuntimeError):
    """Raised when the executable G02 acceptance chain does not meet its contract."""


@dataclass(frozen=True, slots=True)
class G02AcceptanceBundle:
    root: Path
    register_path: Path
    positive_dossier_path: Path
    negative_dossier_path: Path
    verification: dict[str, Any]


def run_g02_acceptance_bundle(
    output_root: str | Path,
    *,
    test_node_file: str | Path,
    test_node_id: str,
) -> G02AcceptanceBundle:
    """Run the synthetic G02 positive and blocking paths and seal their evidence."""
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G02AcceptanceError(f"g02_evidence_root_not_empty:{root}")
    root.mkdir(parents=True, exist_ok=True)
    source_test = Path(test_node_file).resolve()
    if not source_test.is_file():
        raise G02AcceptanceError(f"g02_test_node_file_missing:{source_test}")
    if not test_node_id.startswith("test_") or "::" in test_node_id:
        raise G02AcceptanceError("g02_test_node_id_must_be_a_top_level_pytest_function")

    positive_inputs = _write_positive_fixture(root)
    negative_input = _write_negative_fixture(root)
    config = ExecutionConfig(allowed_roots=(str(root),))
    positive = _run_positive_voyage(root, positive_inputs[0].parent, config)
    negative = _run_negative_voyage(root, negative_input.parent, config)
    positive_report, output_artifacts = _verify_positive_result(root, positive)
    negative_report = _verify_negative_result(root, negative)

    copied_test = root / "test-evidence" / source_test.name
    copied_test.parent.mkdir(parents=True, exist_ok=True)
    copied_test.write_bytes(source_test.read_bytes())
    handoff_path = root / "evidence" / "g02-handoff.json"
    handoff = positive.steps[-1].handoff
    if not isinstance(handoff, dict):
        raise G02AcceptanceError("g02_positive_handoff_missing")
    write_text_artifact(
        handoff_path,
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    input_artifacts = [
        _artifact_receipt(root, path)
        for path in (*positive_inputs, negative_input)
    ]
    output_receipts = [_artifact_receipt(root, path) for path in output_artifacts]
    receipt = {
        "run_id": positive.steps[-1].run_id,
        "input_sha256": artifact_manifest_sha256(input_artifacts),
        "output_sha256": artifact_manifest_sha256(output_receipts),
        "input_artifacts": input_artifacts,
        "output_artifacts": output_receipts,
        "handoff_receipts": [
            {
                "producer": "document_registry",
                "consumer": "synopsis_merge",
                "artifact_path": _relative(root, handoff_path),
                "artifact_sha256": _sha256(handoff_path),
                "status": "verified",
                "evidence": (
                    "Der ausgewählte Quellenumfang und seine Hashes wurden vor dem "
                    "Synopsis-Lauf erneut geprüft."
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
                "name": "medical_synopsis_scope_and_citations",
                "passed": True,
                "evidence": (
                    "PDF und Markdown enthalten beide Schilddrüsenbefunde, den "
                    "Nichtdiagnose-Hinweis und keine Knie- oder Leberfremdquelle."
                ),
            },
            {
                "name": "doctor_directory_complete",
                "passed": True,
                "evidence": (
                    "Das Register enthält für beide relevanten Berichte Name, "
                    "Fachrichtung, Arzt, Kontakt und Befund ohne leere Pflichtzelle."
                ),
            },
            {
                "name": "selected_source_handoff",
                "passed": True,
                "evidence": (
                    "Der Consumer-Run nutzte genau die zwei hashgebundenen, "
                    "themenrelevanten Quellen des Producer-Receipts."
                ),
            },
        ],
        "negative_path": {
            "case": "declared_pdf_page_missing",
            "run_id": negative.steps[0].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "evidence": (
                "Eine deklarierte zweite PDF-Seite fehlte; die Kette stoppte vor "
                "Registerartefakt und Synopsis."
            ),
            "run_report": {
                "path": _relative(root, negative_report),
                "sha256": _sha256(negative_report),
            },
        },
    }

    register = load_gate_register()
    gate = next(item for item in register["gates"] if item["gate_id"] == "G02")
    gate["status"] = "partial"
    gate["evidence"] = {
        "test_nodes": [
            {
                "node": f"{_relative(root, copied_test)}::{test_node_id}",
                "file_sha256": _sha256(copied_test),
            }
        ],
        "run_receipts": [receipt],
    }
    verification = verify_gate_evidence(register, root)
    register_path = root / "gate-register.g02.json"
    write_text_artifact(
        register_path,
        json.dumps(register, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )
    return G02AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(positive.dossier_path),
        negative_dossier_path=Path(negative.dossier_path),
        verification=verification,
    )


def _write_positive_fixture(root: Path) -> tuple[Path, Path, Path]:
    reports = root / "positive" / "inputs" / "fictional-doctor-folder"
    reports.mkdir(parents=True)
    pdf = reports / "01-endokrinologie.pdf"
    pdf.write_bytes(
        _render_pdf(
            "# Tabelle bericht\nPatient: Fallperson 204\n"
            "Fachrichtung: Endokrinologie\n"
            "Arzt: Dr. Mira Beispiel\n"
            "Kontakt: praxis-mira@example.invalid · +49 30 000001\n"
            "Befund: Schilddrüse unauffällig.\n"
        )
    )
    text = reports / "02-orthopaedie.txt"
    text.write_text(
        "Patient: Fallperson 204\nFachrichtung: Orthopädie\n"
        "Befund: Knieverletzung.\n",
        encoding="utf-8",
    )
    database = reports / "03-verlauf.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            'CREATE TABLE bericht ("Patient" TEXT, "Fachrichtung" TEXT, '
            '"Arzt" TEXT, "Kontakt" TEXT, "Befund" TEXT)'
        )
        connection.execute(
            'INSERT INTO bericht VALUES (?, ?, ?, ?, ?)',
            (
                "Fallperson 204",
                "Endokrinologie",
                "Dr. Noa Verlauf",
                "praxis-verlauf@example.invalid · +49 30 000002",
                "Schilddrüse vergrößert",
            ),
        )
        connection.execute(
            'INSERT INTO bericht VALUES (?, ?, ?, ?, ?)',
            (
                "Fallperson 204",
                "Innere Medizin",
                "Dr. Liv Beispiel",
                "praxis-liv@example.invalid · +49 30 000003",
                "Leberwert auffällig",
            ),
        )
    return pdf, text, database


def _write_negative_fixture(root: Path) -> Path:
    reports = root / "negative" / "inputs" / "fictional-doctor-folder"
    reports.mkdir(parents=True)
    pdf = reports / "01-endokrinologie.pdf"
    pdf.write_bytes(
        _render_pdf("Patient: Fallperson 204\nBefund: Schilddrüse unauffällig.\n")
    )
    return pdf


def _run_positive_voyage(
    root: Path,
    reports: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    case = _g02_case(
        reports,
        root / "positive" / "out",
        expected_pages=1,
        title="Schilddrüse · fiktiver Verlauf",
    )
    saved = VoyageStore(base_dir=root, allowed_roots=(str(root),)).save(case)
    return run_voyage(
        saved,
        config,
        run_id="g02_acceptance_positive",
        base_dir=root,
    )


def _run_negative_voyage(
    root: Path,
    reports: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    case = _g02_case(
        reports,
        root / "negative" / "out",
        expected_pages=2,
        title="Schilddrüse · fehlende Seite",
    )
    saved = VoyageStore(base_dir=root, allowed_roots=(str(root),)).save(case)
    return run_voyage(
        saved,
        config,
        run_id="g02_acceptance_missing_page",
        base_dir=root,
    )


def _g02_case(
    reports: Path,
    output_root: Path,
    *,
    expected_pages: int,
    title: str,
) -> dict[str, Any]:
    return {
        "name": title,
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(reports)],
                    "output_dir": str(output_root / "register"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "medical_reports",
                        "topic_filter": ["Schilddrüse"],
                        "source_tables": ["bericht"],
                        "expected_pdf_pages": {
                            "01-endokrinologie.pdf": expected_pages
                        },
                        "formats": ["md"],
                    },
                },
            },
            {
                "workflow": "synopsis_merge",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "synopsis_merge",
                    "input_roots": [str(reports)],
                    "output_dir": str(output_root / "synopsis"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"title": title, "formats": ["md", "pdf"]},
                },
                "handoff": {
                    "format": "document-registry",
                    "mode": "selected_sources",
                },
            },
        ],
    }


def _verify_positive_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, Path, Path]]:
    if result.status != "executed" or len(result.steps) != 2:
        raise G02AcceptanceError("g02_positive_voyage_not_executed")
    handoff = result.steps[-1].handoff or {}
    if handoff.get("status") != "verified":
        raise G02AcceptanceError("g02_positive_handoff_not_verified")
    selected_names = {Path(item["path"]).name for item in handoff.get("source_lineage", [])}
    if selected_names != {"01-endokrinologie.pdf", "03-verlauf.sqlite"}:
        raise G02AcceptanceError("g02_positive_source_scope_mismatch")
    producer_ledger_path = result.steps[0].ledger_path
    if producer_ledger_path is None:
        raise G02AcceptanceError("g02_positive_producer_report_missing")
    producer_report = RunLedger(Path(producer_ledger_path).parent).load(
        result.steps[0].run_id
    )
    registry_path = next(
        (
            Path(item.path)
            for item in producer_report.artifacts
            if item.format == "document-registry"
        ),
        None,
    )
    if registry_path is None:
        raise G02AcceptanceError("g02_positive_registry_missing")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if registry.get("empty_cells") != 0 or registry.get("filled_cells") != 10:
        raise G02AcceptanceError("g02_positive_doctor_directory_incomplete")
    doctor_values = {
        cell["value"]
        for row in registry.get("rows", [])
        for cell in row.get("cells", [])
        if cell.get("column") == "Arzt"
    }
    contact_values = {
        cell["value"]
        for row in registry.get("rows", [])
        for cell in row.get("cells", [])
        if cell.get("column") == "Kontakt"
    }
    if doctor_values != {"Dr. Mira Beispiel", "Dr. Noa Verlauf"}:
        raise G02AcceptanceError("g02_positive_doctor_directory_doctors_mismatch")
    if contact_values != {
        "praxis-mira@example.invalid · +49 30 000001",
        "praxis-verlauf@example.invalid · +49 30 000002",
    }:
        raise G02AcceptanceError("g02_positive_doctor_directory_contacts_mismatch")
    ledger_path = result.steps[-1].ledger_path
    if ledger_path is None:
        raise G02AcceptanceError("g02_positive_run_report_missing")
    report = RunLedger(Path(ledger_path).parent).load(result.steps[-1].run_id)
    if (
        report.coverage is None
        or report.coverage.total_sources != 2
        or report.coverage.read_sources != 2
        or report.coverage.cited_sources != 2
    ):
        raise G02AcceptanceError("g02_positive_coverage_incomplete")
    markdown = next(
        (Path(item.path) for item in report.artifacts if item.format == "markdown"),
        None,
    )
    pdf = next((Path(item.path) for item in report.artifacts if item.format == "pdf"), None)
    if markdown is None or pdf is None:
        raise G02AcceptanceError("g02_positive_outputs_missing")
    markdown_text = markdown.read_text(encoding="utf-8")
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(pdf).pages)
    for expected in (
        "Schilddrüse unauffällig",
        "Schilddrüse vergrößert",
        "keine medizinische Diagnose",
    ):
        if expected not in markdown_text or expected not in pdf_text:
            raise G02AcceptanceError(f"g02_positive_expected_text_missing:{expected}")
    for excluded in ("Knieverletzung", "Leberwert auffällig"):
        if excluded in markdown_text or excluded in pdf_text:
            raise G02AcceptanceError(f"g02_positive_scope_widened:{excluded}")
    return Path(ledger_path), (registry_path, markdown, pdf)


def _verify_negative_result(root: Path, result: VoyageRunResult) -> Path:
    if result.status != "stopped" or len(result.steps) != 1:
        raise G02AcceptanceError("g02_negative_voyage_not_stopped")
    step = result.steps[0]
    if step.status != "blocked" or step.errors != (
        "expected_pdf_page_gap:01-endokrinologie.pdf",
    ):
        raise G02AcceptanceError("g02_negative_reason_mismatch")
    if step.ledger_path is None:
        raise G02AcceptanceError("g02_negative_run_report_missing")
    if (root / "negative" / "out" / "synopsis").exists():
        raise G02AcceptanceError("g02_negative_synopsis_started")
    return Path(step.ledger_path)


def _artifact_receipt(root: Path, path: Path) -> dict[str, str]:
    return {"path": _relative(root, path), "sha256": _sha256(path)}


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise G02AcceptanceError(f"g02_evidence_path_outside_root:{path}") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
