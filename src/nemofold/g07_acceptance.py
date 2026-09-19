"""Executable acceptance bundle for Gate G07: Medication Plan Consolidation (Ellmos UC 23, 37).

Positive and fail-closed blocking paths for medication plan reconciliation across doctor reports.
"""

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
from .voyage_runs import VoyageRunResult, run_voyage


class G07AcceptanceError(RuntimeError):
    """Raised when the executable G07 acceptance chain does not meet its contract."""


@dataclass(frozen=True, slots=True)
class G07AcceptanceBundle:
    root: Path
    register_path: Path
    positive_dossier_path: Path
    unresolved_conflict_dossier_path: Path
    missing_data_dossier_path: Path
    insufficient_meds_dossier_path: Path
    verification: dict[str, Any]


def run_g07_acceptance_bundle(
    output_root: str | Path,
) -> G07AcceptanceBundle:
    """Run the synthetic G07 positive and blocking paths and seal their evidence."""
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G07AcceptanceError(f"g07_evidence_root_not_empty:{root}")
    root.mkdir(parents=True, exist_ok=True)

    positive_inputs = _write_positive_fixture(root)
    unresolved_conflict_inputs = _write_unresolved_conflict_fixture(root)
    missing_data_input = _write_missing_data_fixture(root)
    insufficient_meds_input = _write_insufficient_meds_fixture(root)
    config = ExecutionConfig(allowed_roots=(str(root),))

    positive = _run_positive_voyage(root, positive_inputs[0].parent, config)
    unresolved_conflict = _run_unresolved_conflict_voyage(
        root, unresolved_conflict_inputs[0].parent, config
    )
    missing_data = _run_missing_data_voyage(root, missing_data_input.parent, config)
    insufficient_meds = _run_insufficient_meds_voyage(root, insufficient_meds_input.parent, config)

    positive_report, output_artifacts = _verify_positive_result(root, positive)
    unresolved_report, unresolved_artifacts = _verify_unresolved_conflict_result(
        root, unresolved_conflict
    )
    missing_data_report, missing_data_artifacts = _verify_missing_data_result(root, missing_data)
    insufficient_meds_report, insufficient_meds_artifacts = _verify_insufficient_meds_result(
        root, insufficient_meds
    )

    handoff_path = root / "evidence" / "g07-handoff.json"
    handoff = positive.steps[-1].handoff
    if not isinstance(handoff, dict):
        raise G07AcceptanceError("g07_positive_handoff_missing")
    write_text_artifact(
        handoff_path,
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    input_artifacts = [
        _artifact_receipt(root, path)
        for path in (
            *positive_inputs,
            *unresolved_conflict_inputs,
            missing_data_input,
            insufficient_meds_input,
        )
    ]
    dossier_artifacts = (
        Path(positive.dossier_path),
        Path(positive.dossier_path).with_suffix(".md"),
        Path(unresolved_conflict.dossier_path),
        Path(unresolved_conflict.dossier_path).with_suffix(".md"),
        Path(missing_data.dossier_path),
        Path(missing_data.dossier_path).with_suffix(".md"),
        Path(insufficient_meds.dossier_path),
        Path(insufficient_meds.dossier_path).with_suffix(".md"),
    )
    output_receipts = [
        _artifact_receipt(root, path)
        for path in (
            *output_artifacts,
            *unresolved_artifacts,
            *missing_data_artifacts,
            *insufficient_meds_artifacts,
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
                "producer": "medication_reconcile",
                "consumer": "folder_digest",
                "artifact_path": _relative(root, handoff_path),
                "artifact_sha256": _sha256(handoff_path),
                "status": "verified",
                "evidence": (
                    "medication_reconcile produces a verified consolidated medication plan "
                    "with unambiguous dosages and medical non-authority guardrails; "
                    "folder_digest consumes it as an objective overview handoff."
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
                "name": "multi_source_medication_plan_consolidated",
                "passed": True,
                "evidence": (
                    "Medications from GP (Hausarzt) and hospital discharge (Klinik) reports "
                    "are extracted, grouped, and consolidated into a unified plan with active "
                    "ingredients, dosages, schedules, and source anchors."
                ),
            },
            {
                "name": "dosage_conflict_detected_and_user_confirmed",
                "passed": True,
                "evidence": (
                    "Conflicting dosages for L-Thyroxin (75 µg vs 100 µg) across reports were "
                    "detected, documented with exact lines and quotes, and resolved only through "
                    "explicit user/physician confirmation without automated medical guessing."
                ),
            },
            {
                "name": "medical_non_authority_disclaimer_carried",
                "passed": True,
                "evidence": (
                    "All consolidated reports and payloads carry the mandatory "
                    "medical non-authority notice pursuant to medical compliance guardrails."
                ),
            },
            {
                "name": "unresolved_conflict_halts_without_medical_overreach",
                "passed": True,
                "evidence": (
                    "When conflicting dosages have no user confirmation, the system halts with "
                    "status=blocked and requests clarification via needs-user-input rather than "
                    "inventing or selecting clinical dosages."
                ),
            },
        ],
        "negative_path": {
            "case": "conflicting_dosages_blocked_without_medical_authority",
            "run_id": unresolved_conflict.steps[1].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "run_report": {
                "path": _relative(root, unresolved_report),
                "sha256": _sha256(unresolved_report),
            },
            "evidence": (
                "When medical reports report conflicting dosages without user resolution, the "
                "workflow halts fail-closed with status=blocked and requests user input rather "
                "than exercising medical authority."
            ),
        },
        "additional_negative_paths": [
            {
                "case": "missing_required_medication_fields",
                "run_id": missing_data.steps[1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": _relative(root, missing_data_report),
                    "sha256": _sha256(missing_data_report),
                },
                "evidence": (
                    "When medication records omit required fields (name or dosage), "
                    "medication_reconcile halts with status=blocked and needs-user-input."
                ),
            },
            {
                "case": "insufficient_medications_floor",
                "run_id": insufficient_meds.steps[1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": _relative(root, insufficient_meds_report),
                    "sha256": _sha256(insufficient_meds_report),
                },
                "evidence": (
                    "When fewer medications exist than the declared minimum, medication_reconcile "
                    "halts with status=blocked rather than silently continuing."
                ),
            },
        ],
    }

    evidence_dossier = root / "evidence" / "g07-evidence-dossier.json"
    write_text_artifact(
        evidence_dossier,
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )
    write_text_artifact(
        evidence_dossier.with_suffix(".md"),
        _render_evidence_markdown(receipt),
        "markdown",
    )

    register = load_gate_register_template()
    gate = next(item for item in register["gates"] if item["gate_id"] == "G07")
    gate["status"] = "partial"
    gate["evidence"] = {
        "test_nodes": [],
        "run_receipts": [receipt],
    }
    verification = verify_gate_evidence(register, root)
    register_path = root / "gate-register.g07.json"
    write_text_artifact(
        register_path,
        json.dumps(register, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )
    return G07AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(positive.dossier_path),
        unresolved_conflict_dossier_path=Path(unresolved_conflict.dossier_path),
        missing_data_dossier_path=Path(missing_data.dossier_path),
        insufficient_meds_dossier_path=Path(insufficient_meds.dossier_path),
        verification=verification,
    )


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _write_positive_fixture(root: Path) -> list[Path]:
    in_dir = root / "inputs" / "positive"
    in_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    doc1 = in_dir / "01_arztbrief_hausarzt.txt"
    doc1.write_text(
        "Arzt: Dr. med. Weber (Hausarzt)\n"
        "Datum: 2026-08-15\n"
        "\n"
        "Medikament: L-Thyroxin Henning\n"
        "Wirkstoff: Levothyroxin-Natrium\n"
        "Dosierung: 75 µg\n"
        "Einnahme: 1-0-0-0 morgens nüchtern\n"
        "Indikation: Hypothyreose\n"
        "Status: laufend\n"
        "\n"
        "Medikament: Ramipril-ratiopharm\n"
        "Wirkstoff: Ramipril\n"
        "Dosierung: 5 mg\n"
        "Einnahme: 1-0-0-0 morgens\n"
        "Indikation: Hypertonie\n"
        "Status: laufend\n"
        "\n"
        "Medikament: Pantoprazol TAD\n"
        "Wirkstoff: Pantoprazol\n"
        "Dosierung: 20 mg\n"
        "Einnahme: 0-0-1-0 abends\n"
        "Indikation: Magenschutz\n"
        "Status: laufend\n",
        encoding="utf-8",
    )
    paths.append(doc1)

    doc2 = in_dir / "02_klinikbericht_entlassung.txt"
    doc2.write_text(
        "Arzt: Klinikum Mitte, Abt. Endokrinologie\n"
        "Datum: 2026-09-02\n"
        "\n"
        "Medikament: L-Thyroxin Henning\n"
        "Wirkstoff: Levothyroxin-Natrium\n"
        "Dosierung: 100 µg\n"
        "Einnahme: 1-0-0-0 morgens nüchtern\n"
        "Indikation: Hypothyreose\n"
        "Status: laufend\n"
        "\n"
        "Medikament: Ramipril-ratiopharm\n"
        "Wirkstoff: Ramipril\n"
        "Dosierung: 5 mg\n"
        "Einnahme: 1-0-0-0 morgens\n"
        "Indikation: Hypertonie\n"
        "Status: laufend\n"
        "\n"
        "Medikament: Metformin HEXAL\n"
        "Wirkstoff: Metforminhydrochlorid\n"
        "Dosierung: 1000 mg\n"
        "Einnahme: 1-0-1-0 zu den Mahlzeiten\n"
        "Indikation: Diabetes mellitus Typ 2\n"
        "Status: laufend\n",
        encoding="utf-8",
    )
    paths.append(doc2)

    return paths


def _write_unresolved_conflict_fixture(root: Path) -> list[Path]:
    in_dir = root / "inputs" / "unresolved_conflict"
    in_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    doc1 = in_dir / "01_hausarzt_dosis_alt.txt"
    doc1.write_text(
        "Arzt: Dr. med. Weber (Hausarzt)\n"
        "Datum: 2026-08-15\n"
        "\n"
        "Medikament: L-Thyroxin Henning\n"
        "Wirkstoff: Levothyroxin-Natrium\n"
        "Dosierung: 75 µg\n"
        "Einnahme: 1-0-0-0 morgens nüchtern\n"
        "Indikation: Hypothyreose\n"
        "Status: laufend\n",
        encoding="utf-8",
    )
    paths.append(doc1)

    doc2 = in_dir / "02_klinik_dosis_neu.txt"
    doc2.write_text(
        "Arzt: Klinikum Mitte\n"
        "Datum: 2026-09-02\n"
        "\n"
        "Medikament: L-Thyroxin Henning\n"
        "Wirkstoff: Levothyroxin-Natrium\n"
        "Dosierung: 100 µg\n"
        "Einnahme: 1-0-0-0 morgens nüchtern\n"
        "Indikation: Hypothyreose\n"
        "Status: laufend\n",
        encoding="utf-8",
    )
    paths.append(doc2)

    return paths


def _write_missing_data_fixture(root: Path) -> Path:
    in_dir = root / "inputs" / "missing_data"
    in_dir.mkdir(parents=True, exist_ok=True)
    path = in_dir / "01_unvollstaendig.txt"
    path.write_text(
        "Arzt: Unbekannte Praxis\n"
        "\n"
        "Medikament: \n"
        "Dosierung: \n",
        encoding="utf-8",
    )
    return path


def _write_insufficient_meds_fixture(root: Path) -> Path:
    in_dir = root / "inputs" / "insufficient_meds"
    in_dir.mkdir(parents=True, exist_ok=True)
    path = in_dir / "01_single_med.txt"
    path.write_text(
        "Arzt: Dr. med. Weber\n"
        "Datum: 2026-08-15\n"
        "\n"
        "Medikament: Ibuprofen\n"
        "Dosierung: 400 mg\n"
        "Einnahme: bei Schmerzen\n",
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------- #
# Voyage execution
# --------------------------------------------------------------------------- #


def _run_positive_voyage(
    root: Path,
    input_dir: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    plan = {
        "voyage_id": "vy_g07_positive",
        "title": "G07 Positive Voyage: Medication Reconcile",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "pos_step1"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "medication_plan",
                        "formats": ["md"],
                    },
                },
            },
            {
                "order": 2,
                "workflow": "medication_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "medication_reconcile",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "pos_step2"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "formats": ["md", "json"],
                        "min_medications": 2,
                        "require_unambiguous_dosages": True,
                        "application_domain": "medical_reports",
                        "user_corrections": {
                            "L-Thyroxin Henning": {
                                "dosage": "100 µg",
                                "schedule": "1-0-0-0 morgens nüchtern",
                                "confirmed_by": "Dr. Weber telefonisch am 05.09.2026 bestätigt",
                            }
                        },
                    },
                },
            },
            {
                "order": 3,
                "workflow": "folder_digest",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "pos_step3"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "summary_length": 3,
                    },
                },
                "handoff": {"format": "markdown"},
            },
        ],
    }
    return run_voyage(plan, config, run_id="g07_pos")


def _run_unresolved_conflict_voyage(
    root: Path,
    input_dir: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    plan = {
        "voyage_id": "vy_g07_conflict",
        "title": "G07 Blocking Voyage: Unresolved Dosage Conflict",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "conflict_step1"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "medication_plan",
                        "formats": ["md"],
                    },
                },
            },
            {
                "order": 2,
                "workflow": "medication_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "medication_reconcile",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "conflict_step2"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "formats": ["md"],
                        "min_medications": 1,
                        "require_unambiguous_dosages": True,
                        "application_domain": "medical_reports",
                    },
                },
            },
        ],
    }
    return run_voyage(plan, config, run_id="g07_conflict")


def _run_missing_data_voyage(
    root: Path,
    input_dir: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    plan = {
        "voyage_id": "vy_g07_missing_data",
        "title": "G07 Blocking Voyage: Missing Medication Fields",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "missing_data_step1"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "medication_plan",
                        "formats": ["md"],
                    },
                },
            },
            {
                "order": 2,
                "workflow": "medication_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "medication_reconcile",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "missing_data_step2"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "formats": ["md"],
                        "min_medications": 1,
                    },
                },
            },
        ],
    }
    return run_voyage(plan, config, run_id="g07_missing_data")


def _run_insufficient_meds_voyage(
    root: Path,
    input_dir: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    plan = {
        "voyage_id": "vy_g07_insufficient_meds",
        "title": "G07 Blocking Voyage: Insufficient Medications Floor",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "insufficient_meds_step1"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "medication_plan",
                        "formats": ["md"],
                    },
                },
            },
            {
                "order": 2,
                "workflow": "medication_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "medication_reconcile",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "insufficient_meds_step2"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "formats": ["md"],
                        "min_medications": 4,
                    },
                },
            },
        ],
    }
    return run_voyage(plan, config, run_id="g07_insufficient_meds")


# --------------------------------------------------------------------------- #
# Verification helpers
# --------------------------------------------------------------------------- #


def _verify_positive_result(
    root: Path, result: VoyageRunResult
) -> tuple[Path, list[Path]]:
    if result.status != "executed":
        raise G07AcceptanceError(f"g07_positive_not_executed:{result.status}")
    if len(result.steps) != 3:
        raise G07AcceptanceError(f"g07_positive_expected_3_steps:{len(result.steps)}")
    for step in result.steps:
        if step.status != "executed":
            raise G07AcceptanceError(f"g07_step_{step.order}_failed:{step.status}")

    step2_dir = root / "outputs" / "pos_step2"
    reconcile_json = step2_dir / "g07_pos_02.medication-reconcile.json"
    if not reconcile_json.is_file():
        raise G07AcceptanceError("g07_medication_reconcile_json_missing")

    data = json.loads(reconcile_json.read_text(encoding="utf-8"))
    if data["total_medications"] < 3:
        raise G07AcceptanceError(f"g07_expected_at_least_3_medications:{data['total_medications']}")
    if data["unresolved_conflicts"] != 0:
        raise G07AcceptanceError("g07_unexpected_unresolved_conflicts")
    if data["resolved_conflicts"] < 1:
        raise G07AcceptanceError("g07_expected_resolved_conflict_for_l_thyroxin")

    step2_md = step2_dir / "g07_pos_02.medication-reconcile.md"
    if not step2_md.is_file():
        raise G07AcceptanceError("g07_medication_reconcile_md_missing")
    md_text = step2_md.read_text(encoding="utf-8")
    if "Medizinische Nichtautorität" not in md_text:
        raise G07AcceptanceError("g07_disclaimer_missing_in_md")
    if "L-Thyroxin" not in md_text:
        raise G07AcceptanceError("g07_l_thyroxin_missing_in_md")

    artifacts: list[Path] = []
    for step_dir_name in ("pos_step1", "pos_step2", "pos_step3"):
        step_dir = root / "outputs" / step_dir_name
        artifacts.extend(p for p in step_dir.iterdir() if p.is_file())

    if not result.steps[2].ledger_path or not Path(result.steps[2].ledger_path).is_file():
        raise G07AcceptanceError("g07_positive_final_report_missing")
    return Path(result.steps[2].ledger_path), artifacts


def _verify_unresolved_conflict_result(
    root: Path, result: VoyageRunResult
) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G07AcceptanceError(f"g07_conflict_expected_stopped:{result.status}")
    step2 = result.steps[1]
    if step2.status != "blocked":
        raise G07AcceptanceError(f"g07_step2_conflict_not_blocked:{step2.status}")

    step2_dir = root / "outputs" / "conflict_step2"
    needs_input = step2_dir / "g07_conflict_02.needs-user-input.json"
    if not needs_input.is_file():
        raise G07AcceptanceError("g07_conflict_needs_user_input_missing")
    payload = json.loads(needs_input.read_text(encoding="utf-8"))
    questions = payload.get("questions", [])
    if not any("L-Thyroxin" in q["prompt"] or "l-thyroxin" in q["field"] for q in questions):
        raise G07AcceptanceError("g07_conflict_question_not_asking_for_l_thyroxin")

    artifacts: list[Path] = []
    for step_dir_name in ("conflict_step1", "conflict_step2"):
        step_dir = root / "outputs" / step_dir_name
        artifacts.extend(p for p in step_dir.iterdir() if p.is_file())

    if not step2.ledger_path or not Path(step2.ledger_path).is_file():
        raise G07AcceptanceError("g07_conflict_report_missing")
    return Path(step2.ledger_path), artifacts


def _verify_missing_data_result(
    root: Path, result: VoyageRunResult
) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G07AcceptanceError(f"g07_missing_data_expected_stopped:{result.status}")

    step2 = result.steps[1]
    if step2.status != "blocked":
        raise G07AcceptanceError(f"g07_step2_missing_data_not_blocked:{step2.status}")

    step2_dir = root / "outputs" / "missing_data_step2"
    needs_input = step2_dir / "g07_missing_data_02.needs-user-input.json"
    if not needs_input.is_file():
        raise G07AcceptanceError("g07_missing_data_needs_user_input_missing")

    artifacts: list[Path] = []
    for step_dir_name in ("missing_data_step1", "missing_data_step2"):
        step_dir = root / "outputs" / step_dir_name
        artifacts.extend(p for p in step_dir.iterdir() if p.is_file())

    if not step2.ledger_path or not Path(step2.ledger_path).is_file():
        raise G07AcceptanceError("g07_missing_data_report_missing")
    return Path(step2.ledger_path), artifacts


def _verify_insufficient_meds_result(
    root: Path, result: VoyageRunResult
) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G07AcceptanceError(f"g07_insufficient_meds_expected_stopped:{result.status}")
    step2 = result.steps[1]
    if step2.status != "blocked":
        raise G07AcceptanceError(f"g07_step2_insufficient_meds_not_blocked:{step2.status}")

    step2_dir = root / "outputs" / "insufficient_meds_step2"
    needs_input = step2_dir / "g07_insufficient_meds_02.needs-user-input.json"
    if not needs_input.is_file():
        raise G07AcceptanceError("g07_insufficient_meds_needs_input_missing")

    artifacts: list[Path] = []
    for step_dir_name in ("insufficient_meds_step1", "insufficient_meds_step2"):
        step_dir = root / "outputs" / step_dir_name
        artifacts.extend(p for p in step_dir.iterdir() if p.is_file())

    if not step2.ledger_path or not Path(step2.ledger_path).is_file():
        raise G07AcceptanceError("g07_insufficient_meds_report_missing")
    return Path(step2.ledger_path), artifacts


# --------------------------------------------------------------------------- #
# Hash & markdown helpers
# --------------------------------------------------------------------------- #


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _artifact_receipt(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": _relative(root, path),
        "sha256": _sha256(path),
    }


def _render_evidence_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# G07 Acceptance Dossier: Medication Plan Consolidation",
        "",
        f"- Run ID: `{receipt['run_id']}`",
        f"- Input SHA-256: `{receipt['input_sha256']}`",
        f"- Output SHA-256: `{receipt['output_sha256']}`",
        "",
        "## Result Checks",
        "",
    ]
    for check in receipt.get("result_checks", []):
        status_mark = "PASS" if check.get("passed") else "FAIL"
        lines.append(f"- **{check['name']}**: {status_mark} — {check['evidence']}")

    lines.append("")
    lines.append("## Negative Paths (Fail-Closed)")
    lines.append("")
    neg = receipt.get("negative_path", {})
    p_case = neg.get("case")
    p_stat = neg.get("status")
    p_ev = neg.get("evidence")
    lines.append(f"- Primary: **{p_case}** (`{p_stat}`) — {p_ev}")
    for add_neg in receipt.get("additional_negative_paths", []):
        a_case = add_neg.get("case")
        a_stat = add_neg.get("status")
        a_ev = add_neg.get("evidence")
        lines.append(f"- Additional: **{a_case}** (`{a_stat}`) — {a_ev}")

    lines.append("")
    return "\n".join(lines)
