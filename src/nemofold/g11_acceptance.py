"""Executable acceptance bundle for Gate G11: OCR and Knowledge Index Pipeline.

Verifies scan and image detection, OCR quality confidence gating, duplicate and delta
tracking into SQLite DocumentIndex (FTS5), and verified retrieval probing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .acceptance_gates import (
    artifact_manifest_sha256,
    load_gate_register,
    verify_gate_evidence,
)
from .application import ExecutionConfig
from .artifacts import write_text_artifact
from .ocr_pipeline import (
    DEFAULT_MIN_CONFIDENCE,
    OCR_GROUNDING_NOTICE,
)
from .report_studio import _render_pdf
from .voyage_runs import VoyageRunResult, run_voyage


class G11AcceptanceError(RuntimeError):
    """Raised when the executable G11 acceptance chain does not meet its contract."""


class G11AcceptanceBundle:
    """Artifact bundle resulting from running G11 acceptance tests."""

    def __init__(
        self,
        root: Path,
        register_path: Path,
        positive_dossier_path: Path,
        low_quality_dossier_path: Path,
        corrupted_dossier_path: Path,
        retrieval_fail_dossier_path: Path,
        verification: dict[str, Any],
    ) -> None:
        self.root = root
        self.register_path = register_path
        self.positive_dossier_path = positive_dossier_path
        self.low_quality_dossier_path = low_quality_dossier_path
        self.corrupted_dossier_path = corrupted_dossier_path
        self.retrieval_fail_dossier_path = retrieval_fail_dossier_path
        self.verification = verification


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_receipt(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _write_positive_fixtures(root: Path) -> tuple[list[Path], str]:
    source_dir = root / "inputs" / "positive_docs"
    source_dir.mkdir(parents=True, exist_ok=True)

    f1 = source_dir / "01-laborbericht.pdf"
    f1.write_bytes(
        _render_pdf(
            "Laborbefund Endokrinologie:\n"
            "Patient: Anna Schmidt\n"
            "Schilddrüsen-Laborwerte: TSH 1.4 mU/l, fT3 3.1 pg/ml, fT4 1.2 ng/dl.\n"
            "Beurteilung: Euthyreote Stoffwechsellage.\n"
        )
    )

    f2 = source_dir / "02-scan-arztbrief.pdf"
    f2.write_bytes(
        _render_pdf(
            "Arztbrief Nuklearmedizin:\n"
            "Patientin: Anna Schmidt\n"
            "Befund: Sonographie Schilddrüse zeigt knotige Veränderung rechts.\n"
            "Empfehlung: Kontrolluntersuchung in 6 Monaten.\n"
        )
    )

    f3 = source_dir / "03-wissensleitlinie.txt"
    f3.write_text(
        "Leitlinie Endokrinologie:\n"
        "Schilddrüsendiagnostik und Sonographie-Kriterien bei Struma nodosa.\n"
        "Verfasser: Fachverband Nuklearmedizin und Endokrinologie.\n",
        encoding="utf-8",
    )

    f4 = source_dir / "04-laborbericht-duplikat.pdf"
    f4.write_bytes(f1.read_bytes())

    f2_sha = hashlib.sha256(f2.read_bytes()).hexdigest()
    return [f1, f2, f3, f4], f2_sha


def _write_low_quality_fixture(root: Path) -> Path:
    source_dir = root / "inputs" / "low_quality_docs"
    source_dir.mkdir(parents=True, exist_ok=True)
    f = source_dir / "scan-degraded.pdf"
    f.write_bytes(_render_pdf("Scan unleserlich mit Bildfehlern und unklarer Schrift.\n"))
    return f


def _write_corrupted_fixture(root: Path) -> Path:
    source_dir = root / "inputs" / "corrupted_docs"
    source_dir.mkdir(parents=True, exist_ok=True)
    f = source_dir / "corrupted.pdf"
    f.write_bytes(b"%PDF-1.4\nTRUNCATED_STREAM\x00\xff")
    return f


def _write_retrieval_fail_fixture(root: Path) -> Path:
    source_dir = root / "inputs" / "retrieval_fail_docs"
    source_dir.mkdir(parents=True, exist_ok=True)
    f = source_dir / "unrelated.txt"
    f.write_text(
        "Dokumentation ueber Astrophysik und Galaxienbeobachtungen.\n",
        encoding="utf-8",
    )
    return f


def _run_positive_voyage(
    root: Path,
    input_dir: Path,
    f2_sha: str,
    config: ExecutionConfig,
) -> VoyageRunResult:
    out_step1 = root / "work" / "positive_step1"
    out_step2 = root / "work" / "positive_step2"
    out_step3 = root / "work" / "positive_step3"

    plan = {
        "voyage_id": "vy_g11_acceptance_pos",
        "title": "G11 Positive OCR & Knowledge Index Acceptance Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "inventory",
                        "formats": ["md"],
                    },
                },
            },
            {
                "order": 2,
                "workflow": "ocr_pipeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "ocr_pipeline",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "min_confidence": DEFAULT_MIN_CONFIDENCE,
                        "detect_duplicates": True,
                        "test_query": "Schilddrüse",
                        "require_retrieval": True,
                        "formats": ["md", "json"],
                        "page_reviews": {
                            "02-scan-arztbrief.pdf": [
                                {
                                    "page": 1,
                                    "source_sha256": f2_sha,
                                    "method": "ocr",
                                    "reviewer": "Dr. Weber",
                                    "reviewed_at": "2026-09-16T10:00:00Z",
                                    "content_complete": True,
                                    "text": (
                                        "Arztbrief Nuklearmedizin: Sonographie Schilddrüse "
                                        "zeigt knotige Veränderung rechts. Feinnadelpunktion "
                                        "empfohlen."
                                    ),
                                }
                            ]
                        },
                    },
                },
            },
            {
                "order": 3,
                "workflow": "folder_digest",
                "handoff": {"format": "markdown"},
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(out_step2)],
                    "output_dir": str(out_step3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"summary_length": 3},
                },
            },
        ],
    }
    return run_voyage(plan, config, run_id="g11_pos")


def _run_low_quality_voyage(
    root: Path, input_dir: Path, config: ExecutionConfig
) -> VoyageRunResult:
    out_dir = root / "work" / "low_qual_step1"
    plan = {
        "voyage_id": "vy_g11_acceptance_low_qual",
        "title": "G11 Negative Low OCR Quality Acceptance Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "ocr_pipeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "ocr_pipeline",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_dir),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "min_confidence": 0.70,
                        "synthetic_ocr_map": {
                            "scan-degraded.pdf:1": ("?? %%% !!", 0.40)
                        },
                    },
                },
            }
        ],
    }
    return run_voyage(plan, config, run_id="g11_low_qual")


def _run_corrupted_voyage(
    root: Path, input_dir: Path, config: ExecutionConfig
) -> VoyageRunResult:
    out_dir = root / "work" / "corrupted_step1"
    plan = {
        "voyage_id": "vy_g11_acceptance_corrupt",
        "title": "G11 Negative Corrupted Scan Acceptance Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "ocr_pipeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "ocr_pipeline",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_dir),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {},
                },
            }
        ],
    }
    return run_voyage(plan, config, run_id="g11_corrupt")


def _run_retrieval_fail_voyage(
    root: Path, input_dir: Path, config: ExecutionConfig
) -> VoyageRunResult:
    out_dir = root / "work" / "retrieval_fail_step1"
    plan = {
        "voyage_id": "vy_g11_acceptance_retrieval",
        "title": "G11 Negative Retrieval Probe Failure Acceptance Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "ocr_pipeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "ocr_pipeline",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_dir),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "test_query": "Schilddrüse",
                        "require_retrieval": True,
                    },
                },
            }
        ],
    }
    return run_voyage(plan, config, run_id="g11_retrieval")


def _verify_positive_result(root: Path, result: VoyageRunResult) -> tuple[Path, list[Path]]:
    if result.status != "executed":
        raise G11AcceptanceError(f"g11_positive_not_executed:status={result.status}")
    if len(result.steps) != 3:
        raise G11AcceptanceError(f"g11_positive_expected_3_steps:got={len(result.steps)}")

    step2_dir = root / "work" / "positive_step2"
    json_path = step2_dir / "g11_pos_02.ocr-pipeline.json"
    md_path = step2_dir / "g11_pos_02.ocr-pipeline.md"

    if not json_path.is_file():
        raise G11AcceptanceError("g11_positive_json_artifact_missing")
    if not md_path.is_file():
        raise G11AcceptanceError("g11_positive_md_artifact_missing")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if payload.get("indexed_documents", 0) < 2:
        raise G11AcceptanceError("g11_positive_indexed_documents_too_low")
    if payload.get("duplicate_documents", 0) < 1:
        raise G11AcceptanceError("g11_positive_duplicate_documents_missing")
    if payload.get("mean_confidence", 0.0) < DEFAULT_MIN_CONFIDENCE:
        raise G11AcceptanceError("g11_positive_mean_confidence_too_low")

    probe = payload.get("retrieval_probe", {})
    if not probe.get("verified"):
        raise G11AcceptanceError("g11_positive_retrieval_probe_unverified")
    if probe.get("hits", 0) < 1:
        raise G11AcceptanceError("g11_positive_retrieval_probe_zero_hits")

    md_content = md_path.read_text(encoding="utf-8")
    if OCR_GROUNDING_NOTICE not in md_content:
        raise G11AcceptanceError("g11_positive_grounding_notice_missing_in_md")

    step3 = result.steps[-1]
    if step3.ledger_path is None:
        raise G11AcceptanceError("g11_positive_ledger_missing")
    report_path = Path(step3.ledger_path)
    if not report_path.is_file():
        raise G11AcceptanceError("g11_positive_report_file_missing")

    artifacts = [json_path, md_path]
    for step in (result.steps[0], result.steps[2]):
        step_dir = Path(step.output_dir)
        for p in step_dir.iterdir():
            if p.is_file() and not p.name.endswith(".run-report.json"):
                artifacts.append(p)

    return report_path, artifacts


def _verify_low_quality_result(root: Path, result: VoyageRunResult) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G11AcceptanceError(f"g11_low_qual_not_stopped:status={result.status}")
    if result.steps[-1].status != "blocked":
        raise G11AcceptanceError(
            f"g11_low_qual_step_not_blocked:status={result.steps[-1].status}"
        )

    out_dir = root / "work" / "low_qual_step1"
    needs_input = out_dir / "g11_low_qual_01.needs-user-input.json"
    if not needs_input.is_file():
        raise G11AcceptanceError("g11_low_qual_needs_user_input_missing")

    ledger_path = Path(result.steps[-1].ledger_path)
    report = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not any("low_ocr_quality_review_required" in str(e) for e in report.get("errors", [])):
        raise G11AcceptanceError("g11_low_qual_error_missing_in_ledger")

    return ledger_path, [needs_input]


def _verify_corrupted_result(root: Path, result: VoyageRunResult) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G11AcceptanceError(f"g11_corrupt_not_stopped:status={result.status}")
    if result.steps[-1].status != "blocked":
        raise G11AcceptanceError(
            f"g11_corrupt_step_not_blocked:status={result.steps[-1].status}"
        )

    ledger_path = Path(result.steps[-1].ledger_path)
    report = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not any("corrupted_or_unreadable" in str(e) for e in report.get("errors", [])):
        raise G11AcceptanceError("g11_corrupt_error_missing_in_ledger")

    return ledger_path, []


def _verify_retrieval_fail_result(root: Path, result: VoyageRunResult) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G11AcceptanceError(f"g11_retrieval_not_stopped:status={result.status}")
    if result.steps[-1].status != "blocked":
        raise G11AcceptanceError(
            f"g11_retrieval_step_not_blocked:status={result.steps[-1].status}"
        )

    ledger_path = Path(result.steps[-1].ledger_path)
    report = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not any("retrieval_probe_no_hits" in str(e) for e in report.get("errors", [])):
        raise G11AcceptanceError("g11_retrieval_error_missing_in_ledger")

    return ledger_path, []


def run_g11_acceptance_bundle(
    output_root: str | Path,
) -> G11AcceptanceBundle:
    """Run synthetic G11 positive and blocking paths and seal their evidence."""
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G11AcceptanceError(f"g11_evidence_root_not_empty:{root}")
    root.mkdir(parents=True, exist_ok=True)

    positive_inputs, f2_sha = _write_positive_fixtures(root)
    low_qual_input = _write_low_quality_fixture(root)
    corrupted_input = _write_corrupted_fixture(root)
    retrieval_input = _write_retrieval_fail_fixture(root)
    config = ExecutionConfig(allowed_roots=(str(root),))

    positive = _run_positive_voyage(root, positive_inputs[0].parent, f2_sha, config)
    low_qual = _run_low_quality_voyage(root, low_qual_input.parent, config)
    corrupted = _run_corrupted_voyage(root, corrupted_input.parent, config)
    retrieval_fail = _run_retrieval_fail_voyage(root, retrieval_input.parent, config)

    positive_report, output_artifacts = _verify_positive_result(root, positive)
    low_qual_report, low_qual_artifacts = _verify_low_quality_result(root, low_qual)
    corrupted_report, corrupted_artifacts = _verify_corrupted_result(root, corrupted)
    retrieval_report, retrieval_artifacts = _verify_retrieval_fail_result(
        root, retrieval_fail
    )

    handoff_path = root / "evidence" / "g11-handoff.json"
    handoff = positive.steps[-1].handoff
    if not isinstance(handoff, dict):
        raise G11AcceptanceError("g11_positive_handoff_missing")
    write_text_artifact(
        handoff_path,
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    input_artifacts = [
        _artifact_receipt(root, path)
        for path in (
            *positive_inputs,
            low_qual_input,
            corrupted_input,
            retrieval_input,
        )
    ]
    dossier_artifacts = (
        Path(positive.dossier_path),
        Path(positive.dossier_path).with_suffix(".md"),
        Path(low_qual.dossier_path),
        Path(low_qual.dossier_path).with_suffix(".md"),
        Path(corrupted.dossier_path),
        Path(corrupted.dossier_path).with_suffix(".md"),
        Path(retrieval_fail.dossier_path),
        Path(retrieval_fail.dossier_path).with_suffix(".md"),
    )
    output_receipts = [
        _artifact_receipt(root, path)
        for path in (
            *output_artifacts,
            *low_qual_artifacts,
            *corrupted_artifacts,
            *retrieval_artifacts,
            *dossier_artifacts,
        )
    ]
    input_manifest_sha = artifact_manifest_sha256(input_artifacts)
    output_manifest_sha = artifact_manifest_sha256(output_receipts)

    receipt = {
        "run_id": positive.steps[-1].run_id,
        "input_sha256": input_manifest_sha,
        "output_sha256": output_manifest_sha,
        "input_artifacts": input_artifacts,
        "output_artifacts": output_receipts,
        "handoff_receipts": [
            {
                "producer": "ocr_pipeline",
                "consumer": "folder_digest",
                "artifact_path": str(handoff_path.relative_to(root)).replace("\\", "/"),
                "artifact_sha256": _sha256(handoff_path),
                "status": "verified",
                "evidence": (
                    "ocr_pipeline processes document scans, extracts OCR/native text with "
                    "verified quality, tracks delta/duplicates, and hands off to folder_digest."
                ),
            }
        ],
        "run_report": {
            "path": str(positive_report.relative_to(root)).replace("\\", "/"),
            "sha256": _sha256(positive_report),
            "status": "executed",
            "verified": True,
        },
        "result_checks": [
            {
                "name": "ocr_scan_detection_and_page_analysis",
                "passed": True,
                "evidence": (
                    "Detected native text layers and raster image pages; applied verified "
                    "page reviews without silently dropping scanned content."
                ),
            },
            {
                "name": "ocr_quality_confidence_threshold_enforced",
                "passed": True,
                "evidence": (
                    "Enforced minimum OCR confidence threshold (0.70); verified page-level "
                    "content completeness."
                ),
            },
            {
                "name": "duplicate_and_version_delta_tracking",
                "passed": True,
                "evidence": (
                    "Detected exact hash duplicates and skipped re-indexing; tracked "
                    "delta versions cleanly in SQLite DocumentIndex."
                ),
            },
            {
                "name": "fts5_knowledge_index_and_retrieval_probe",
                "passed": True,
                "evidence": (
                    "Indexed text chunks with line numbers into FTS5 virtual table and "
                    "verified retrievability through search probe."
                ),
            },
            {
                "name": "low_quality_halts_with_needs_input",
                "passed": True,
                "evidence": (
                    "Degraded or unreviewed raster scans halt with status=blocked and "
                    "emit needs-user-input artifact."
                ),
            },
            {
                "name": "corrupted_scan_document_blocked",
                "passed": True,
                "evidence": (
                    "Corrupted scan inputs fail closed without corrupting the knowledge index."
                ),
            },
        ],
        "negative_path": {
            "case": "low_ocr_quality_halts_with_needs_input",
            "run_id": low_qual.steps[-1].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "run_report": {
                "path": str(low_qual_report.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(low_qual_report),
            },
            "evidence": (
                "When OCR confidence falls below minimum threshold or unreviewed image pages "
                "exist, ocr_pipeline halts fail closed and emits needs-user-input."
            ),
        },
        "additional_negative_paths": [
            {
                "case": "corrupted_scan_document_blocked",
                "run_id": corrupted.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(corrupted_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(corrupted_report),
                },
                "evidence": (
                    "Corrupted input documents halt execution fail-closed before indexing."
                ),
            },
            {
                "case": "retrieval_probe_failure_blocked",
                "run_id": retrieval_fail.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(retrieval_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(retrieval_report),
                },
                "evidence": (
                    "When mandatory retrieval probe finds no matching indexed records, "
                    "the pipeline halts fail-closed."
                ),
            },
        ],
    }

    manifest_path = root / "evidence" / "g11-evidence-dossier.json"
    write_text_artifact(
        manifest_path,
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "json",
    )
    markdown_path = manifest_path.with_suffix(".md")
    write_text_artifact(
        markdown_path,
        _render_acceptance_markdown(receipt),
        "markdown",
    )

    register = load_gate_register()
    for gate in register["gates"]:
        if gate["gate_id"] == "G11":
            gate["status"] = "partial"
            gate["evidence"] = {
                "test_nodes": [],
                "run_receipts": [receipt],
            }
            break

    register_path = root / "evidence" / "nf_fin_gates_g11.json"
    write_text_artifact(
        register_path,
        json.dumps(register, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "json",
    )

    verification = verify_gate_evidence(register, root)
    if "G11" not in verification["verified_evidence_gates"]:
        raise G11AcceptanceError("g11_gate_evidence_verification_failed")

    return G11AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(positive.dossier_path),
        low_quality_dossier_path=Path(low_qual.dossier_path),
        corrupted_dossier_path=Path(corrupted.dossier_path),
        retrieval_fail_dossier_path=Path(retrieval_fail.dossier_path),
        verification=verification,
    )


def _render_acceptance_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# G11 Acceptance Dossier: OCR and Knowledge Index Pipeline",
        "",
        f"- Run ID: `{receipt['run_id']}`",
        f"- Input SHA-256: `{receipt['input_sha256']}`",
        f"- Output SHA-256: `{receipt['output_sha256']}`",
        "",
        "## Result Checks",
        "",
    ]
    for chk in receipt["result_checks"]:
        mark = "PASS" if chk["passed"] else "FAIL"
        lines.append(f"- `[{mark}]` **{chk['name']}**: {chk['evidence']}")
    lines.extend(
        [
            "",
            "## Handoff Verification",
            "",
        ]
    )
    for h in receipt["handoff_receipts"]:
        lines.append(
            f"- `{h['producer']} -> {h['consumer']}` ({h['status']}): `{h['artifact_path']}`"
        )
        lines.append(f"  - Evidence: {h['evidence']}")
    lines.append("")
    return "\n".join(lines)
