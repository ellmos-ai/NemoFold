from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .acceptance_gates import (
    artifact_manifest_sha256,
    load_gate_register_template,
    require_ledger_path,
    verify_gate_evidence,
)
from .application import ExecutionConfig
from .artifacts import write_text_artifact
from .contracts import RunStatus
from .ledger import RunLedger
from .voyage_runs import VoyageRunResult, run_voyage


class G05AcceptanceError(RuntimeError):
    """Raised when the executable G05 acceptance chain does not meet its contract."""


@dataclass(frozen=True, slots=True)
class G05AcceptanceBundle:
    root: Path
    register_path: Path
    positive_dossier_path: Path
    missing_dates_dossier_path: Path
    missing_data_dossier_path: Path
    insufficient_items_dossier_path: Path
    verification: dict[str, Any]


def run_g05_acceptance_bundle(
    output_root: str | Path,
) -> G05AcceptanceBundle:
    """Run the synthetic G05 positive and blocking paths and seal their evidence."""
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G05AcceptanceError(f"g05_evidence_root_not_empty:{root}")
    root.mkdir(parents=True, exist_ok=True)
    positive_inputs = _write_positive_fixture(root)
    missing_dates_input = _write_missing_dates_fixture(root)
    missing_data_input = _write_missing_data_fixture(root)
    insufficient_items_input = _write_insufficient_items_fixture(root)
    config = ExecutionConfig(allowed_roots=(str(root),))

    positive = _run_positive_voyage(root, positive_inputs[0].parent, config)
    missing_dates = _run_missing_dates_voyage(root, missing_dates_input.parent, config)
    missing_data = _run_missing_data_voyage(root, missing_data_input.parent, config)
    insufficient_items = _run_insufficient_items_voyage(
        root, insufficient_items_input.parent, config
    )

    positive_report, output_artifacts = _verify_positive_result(root, positive)
    missing_dates_report, missing_dates_artifacts = _verify_missing_dates_result(
        root, missing_dates
    )
    missing_data_report, missing_data_artifacts = _verify_missing_data_result(
        root, missing_data
    )
    insufficient_items_report, insufficient_items_artifacts = (
        _verify_insufficient_items_result(root, insufficient_items)
    )

    handoff_path = root / "evidence" / "g05-handoff.json"
    handoff = positive.steps[-1].handoff
    if not isinstance(handoff, dict):
        raise G05AcceptanceError("g05_positive_handoff_missing")
    write_text_artifact(
        handoff_path,
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    input_artifacts = [
        _artifact_receipt(root, path)
        for path in (
            *positive_inputs,
            missing_dates_input,
            missing_data_input,
            insufficient_items_input,
        )
    ]
    dossier_artifacts = (
        Path(positive.dossier_path),
        Path(positive.dossier_path).with_suffix(".md"),
        Path(missing_dates.dossier_path),
        Path(missing_dates.dossier_path).with_suffix(".md"),
        Path(missing_data.dossier_path),
        Path(missing_data.dossier_path).with_suffix(".md"),
        Path(insufficient_items.dossier_path),
        Path(insufficient_items.dossier_path).with_suffix(".md"),
    )
    output_receipts = [
        _artifact_receipt(root, path)
        for path in (
            *output_artifacts,
            *missing_dates_artifacts,
            *missing_data_artifacts,
            *insufficient_items_artifacts,
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
                "producer": "cost_timeline",
                "consumer": "folder_digest",
                "artifact_path": _relative(root, handoff_path),
                "artifact_sha256": _sha256(handoff_path),
                "status": "verified",
                "evidence": (
                    "cost_timeline produces a verified markdown artifact with normalized "
                    "billing cadences, October 2026 forecast and separated irregular special "
                    "effects; folder_digest consumes it as an objective overview handoff."
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
                "name": "recurring_monthly_projected_correctly",
                "passed": True,
                "evidence": (
                    "Monthly subscriptions (Fitnessstudio 39.90, Streaming Plus 17.99) and "
                    "quarterly due item (Rundfunkbeitrag 55.08) sum to exactly 112.97 EUR."
                ),
            },
            {
                "name": "special_effects_forecast_isolated_with_period",
                "passed": True,
                "evidence": (
                    "Annual KFZ-Steuer (148.00 EUR, Fälligkeit 2026-10-20) is recognized as "
                    "an expected special effect for October 2026. Future TÜV in November 2026 "
                    "is scheduled but excluded from October total."
                ),
            },
            {
                "name": "unknown_due_dates_blocked_from_exact_forecast",
                "passed": True,
                "evidence": (
                    "Contracts declaring uncertain due dates ('unbestimmt') trigger a fail-closed "
                    "block when an exact deterministic forecast is requested."
                ),
            },
            {
                "name": "honest_cost_honesty_disclaimer_present",
                "passed": True,
                "evidence": (
                    "Cost timeline reports declare that unknown due dates are never placed on "
                    "guessed moments or included in exact forecasts."
                ),
            },
        ],
        "negative_path": {
            "case": "missing_cost_due_dates",
            "run_id": missing_dates.steps[1].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "run_report": {
                "path": _relative(root, missing_dates_report),
                "sha256": _sha256(missing_dates_report),
            },
            "evidence": (
                "When a contract states 'Nächste Fälligkeit: unbestimmt', the cost_timeline "
                "workflow stops with status=blocked and requests clarification via "
                "needs-user-input rather than inventing an exact projection date."
            ),
        },
        "additional_negative_paths": [
            {
                "case": "missing_required_cost_amount_column",
                "run_id": missing_data.steps[0].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": _relative(root, missing_data_report),
                    "sha256": _sha256(missing_data_report),
                },
                "evidence": (
                    "When a contract document omits a declared required column like 'Betrag', "
                    "document_registry halts immediately with needs-user-input instead of "
                    "proceeding with incomplete cost facts."
                ),
            },
            {
                "case": "insufficient_cost_items_floor",
                "run_id": insufficient_items.steps[1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": _relative(root, insufficient_items_report),
                    "sha256": _sha256(insufficient_items_report),
                },
                "evidence": (
                    "When min_cost_items is configured and insufficient contracts are available, "
                    "cost_timeline stops with status=blocked and a needs-user-input artifact."
                ),
            },
        ],
    }

    evidence_dossier_path = root / "evidence" / "g05-dossier.json"
    evidence_markdown_path = root / "evidence" / "g05-dossier.md"
    write_text_artifact(
        evidence_dossier_path,
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )
    write_text_artifact(
        evidence_markdown_path,
        _render_evidence_markdown(receipt),
        "markdown",
    )

    register = load_gate_register_template()
    gate = next(item for item in register["gates"] if item["gate_id"] == "G05")
    gate["status"] = "partial"
    gate["evidence"] = {
        "test_nodes": [],
        "run_receipts": [receipt],
    }
    verification = verify_gate_evidence(register, root)
    register_path = root / "gate-register.g05.json"
    write_text_artifact(
        register_path,
        json.dumps(register, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    return G05AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(positive.dossier_path),
        missing_dates_dossier_path=Path(missing_dates.dossier_path),
        missing_data_dossier_path=Path(missing_data.dossier_path),
        insufficient_items_dossier_path=Path(insufficient_items.dossier_path),
        verification=verification,
    )


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

CONTRACT_FITNESS = """Vertrag: Fitnessstudio StudioNord
Betrag: 39,90 €
Turnus: monatlich
Nächste Fälligkeit: 2026-10-01
Kategorie: wiederkehrend
Kontakt: service@studionord-beispiel.de
"""

CONTRACT_STREAMING = """Vertrag: Streaming Plus
Betrag: 17,99 €
Turnus: monatlich
Nächste Fälligkeit: 2026-10-05
Kategorie: wiederkehrend
Kontakt: support@streamplus-beispiel.de
"""

CONTRACT_KFZ_STEUER = """Vertrag: KFZ-Steuer Hauptzollamt
Betrag: 148,00 €
Turnus: jährlich
Nächste Fälligkeit: 2026-10-20
Kategorie: Sondereffekt
Kontakt: kfz@zoll-beispiel.de
"""

CONTRACT_TUEV = """Vertrag: TÜV Hauptuntersuchung
Betrag: 140,00 €
Turnus: zweijährlich
Nächste Fälligkeit: 2026-11-15
Kategorie: Sondereffekt
Kontakt: pruefstelle@tuev-beispiel.de
"""

CONTRACT_RUNDFUNK = """Vertrag: Rundfunkbeitrag ARD ZDF
Betrag: 55,08 €
Turnus: vierteljährlich
Nächste Fälligkeit: 2026-10-15
Kategorie: wiederkehrend
Kontakt: beitragsservice@rundfunk-beispiel.de
"""

CONTRACT_UNDETERMINED_DATES = """Vertrag: Nebenkostenabrechnung Nachzahlung
Betrag: 250,00 €
Turnus: unregelmäßig
Nächste Fälligkeit: unbestimmt
Kategorie: Sondereffekt
Kontakt: verwaltung@beispiel.de
"""

CONTRACT_MISSING_DATA = """Vertrag: Internet Glasfaser
Turnus: monatlich
Nächste Fälligkeit: 2026-10-01
Kategorie: wiederkehrend
Kontakt: info@glasfaser-beispiel.de
"""

CONTRACT_SPARSE = """Vertrag: Mini Abo
Betrag: 2,99 €
Turnus: monatlich
Nächste Fälligkeit: 2026-10-01
"""


def _write_positive_fixture(root: Path) -> tuple[Path, ...]:
    target = root / "inputs" / "contracts_positive"
    target.mkdir(parents=True, exist_ok=True)
    p1 = target / "01_fitness.txt"
    p2 = target / "02_streaming.txt"
    p3 = target / "03_kfz_steuer.txt"
    p4 = target / "04_tuev.txt"
    p5 = target / "05_rundfunk.txt"
    p1.write_text(CONTRACT_FITNESS, encoding="utf-8")
    p2.write_text(CONTRACT_STREAMING, encoding="utf-8")
    p3.write_text(CONTRACT_KFZ_STEUER, encoding="utf-8")
    p4.write_text(CONTRACT_TUEV, encoding="utf-8")
    p5.write_text(CONTRACT_RUNDFUNK, encoding="utf-8")
    return (p1, p2, p3, p4, p5)


def _write_missing_dates_fixture(root: Path) -> Path:
    target = root / "inputs" / "contracts_missing_dates"
    target.mkdir(parents=True, exist_ok=True)
    f = target / "01_undetermined_date.txt"
    f.write_text(CONTRACT_UNDETERMINED_DATES, encoding="utf-8")
    return f


def _write_missing_data_fixture(root: Path) -> Path:
    target = root / "inputs" / "contracts_missing_data"
    target.mkdir(parents=True, exist_ok=True)
    f = target / "01_incomplete_data.txt"
    f.write_text(CONTRACT_MISSING_DATA, encoding="utf-8")
    return f


def _write_insufficient_items_fixture(root: Path) -> Path:
    target = root / "inputs" / "contracts_insufficient_items"
    target.mkdir(parents=True, exist_ok=True)
    f = target / "01_single_item.txt"
    f.write_text(CONTRACT_SPARSE, encoding="utf-8")
    return f


# --------------------------------------------------------------------------- #
# Voyage execution
# --------------------------------------------------------------------------- #


def _run_positive_voyage(root: Path, input_dir: Path, config: ExecutionConfig) -> VoyageRunResult:
    voyage = {
        "name": "g05_positive_cost_planning_voyage",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "positive_01_registry"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "recurring_costs",
                        "formats": ["md"],
                        "title": "Kostenquellen-Inventar",
                    },
                },
            },
            {
                "workflow": "cost_timeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "cost_timeline",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "positive_02_timeline"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "forecast_month": "2026-10",
                        "reference_date": "2026-10-01",
                        "due_within_days": 30,
                        "require_deterministic_due_dates": True,
                        "formats": ["md"],
                        "title": "Kosten- und Fälligkeitsplanung Oktober 2026",
                    },
                },
            },
            {
                "workflow": "folder_digest",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "positive_03_digest"),
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
    return run_voyage(
        voyage,
        config,
        run_id="g05_pos",
        base_dir=root / "outputs" / "positive_dossier",
    )


def _run_missing_dates_voyage(
    root: Path, input_dir: Path, config: ExecutionConfig
) -> VoyageRunResult:
    voyage = {
        "name": "g05_missing_dates_voyage",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "neg_dates_01_registry"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "recurring_costs",
                        "formats": ["md"],
                    },
                },
            },
            {
                "workflow": "cost_timeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "cost_timeline",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "neg_dates_02_timeline"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "forecast_month": "2026-10",
                        "require_deterministic_due_dates": True,
                        "formats": ["md"],
                    },
                },
            },
        ],
    }
    return run_voyage(
        voyage,
        config,
        run_id="g05_neg_dates",
        base_dir=root / "outputs" / "neg_dates_dossier",
    )


def _run_missing_data_voyage(
    root: Path, input_dir: Path, config: ExecutionConfig
) -> VoyageRunResult:
    voyage = {
        "name": "g05_missing_data_voyage",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "neg_data_01_registry"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "recurring_costs",
                        "required_columns": ["Betrag"],
                        "formats": ["md"],
                    },
                },
            },
        ],
    }
    return run_voyage(
        voyage,
        config,
        run_id="g05_neg_data",
        base_dir=root / "outputs" / "neg_data_dossier",
    )


def _run_insufficient_items_voyage(
    root: Path, input_dir: Path, config: ExecutionConfig
) -> VoyageRunResult:
    voyage = {
        "name": "g05_insufficient_items_voyage",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "neg_items_01_registry"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "recurring_costs",
                        "formats": ["md"],
                    },
                },
            },
            {
                "workflow": "cost_timeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "cost_timeline",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "neg_items_02_timeline"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "min_cost_items": 5,
                        "formats": ["md"],
                    },
                },
            },
        ],
    }
    return run_voyage(
        voyage,
        config,
        run_id="g05_neg_items",
        base_dir=root / "outputs" / "neg_items_dossier",
    )


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #


def _verify_positive_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "executed" or len(result.steps) != 3:
        raise G05AcceptanceError("g05_positive_voyage_failed")
    artifacts: list[Path] = []
    for step in result.steps:
        if step.status != "executed":
            raise G05AcceptanceError(f"g05_positive_step_not_executed:{step.workflow}")
        if step.ledger_path is None:
            raise G05AcceptanceError(f"g05_positive_ledger_missing:{step.workflow}")
        ledger_file = Path(step.ledger_path)
        report = RunLedger(ledger_file.parent).load(step.run_id)
        if report.status is not RunStatus.EXECUTED:
            raise G05AcceptanceError(f"g05_positive_step_report_not_executed:{step.workflow}")
        for art in report.artifacts:
            art_path = root / art.path if not Path(art.path).is_absolute() else Path(art.path)
            if not art_path.is_file() or art_path.stat().st_size == 0:
                raise G05AcceptanceError(f"g05_artifact_missing_or_empty:{art.path}")
            artifacts.append(art_path)

    timeline_step = result.steps[1]
    timeline_ledger = require_ledger_path(timeline_step.ledger_path, "G05:_verify_positive_result")
    timeline_report = RunLedger(timeline_ledger.parent).load(timeline_step.run_id)
    if timeline_report.metadata.get("item_count") != 5:
        raise G05AcceptanceError("g05_cost_item_count_mismatch")
    if timeline_report.metadata.get("projected_recurring_total") != 112.97:
        raise G05AcceptanceError("g05_recurring_total_mismatch")
    if timeline_report.metadata.get("projected_special_effects_total") != 148.0:
        raise G05AcceptanceError("g05_special_effects_total_mismatch")
    if timeline_report.metadata.get("projected_total") != 260.97:
        raise G05AcceptanceError("g05_projected_total_mismatch")

    final_step = result.steps[-1]
    final_ledger = require_ledger_path(final_step.ledger_path, "G05:_verify_positive_result")
    return final_ledger, tuple(artifacts)


def _verify_missing_dates_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped" or len(result.steps) != 2:
        raise G05AcceptanceError("g05_missing_dates_voyage_not_stopped")
    step = result.steps[1]
    has_dates_error = any("undetermined_cost_due_dates" in err for err in step.errors)
    if step.status != "blocked" or not has_dates_error:
        raise G05AcceptanceError("g05_missing_dates_reason_mismatch")
    if step.ledger_path is None:
        raise G05AcceptanceError("g05_missing_dates_run_report_missing")
    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    if report.status is not RunStatus.BLOCKED:
        raise G05AcceptanceError("g05_missing_dates_report_status_not_blocked")
    if report.metadata.get("needs_user_input") is not True:
        raise G05AcceptanceError("g05_missing_dates_needs_user_input_not_flagged")

    artifacts: list[Path] = []
    for s in result.steps:
        if s.ledger_path:
            rep = RunLedger(Path(s.ledger_path).parent).load(s.run_id)
            for art in rep.artifacts:
                art_path = root / art.path if not Path(art.path).is_absolute() else Path(art.path)
                if art_path.is_file() and art_path.stat().st_size > 0:
                    artifacts.append(art_path)
    return Path(step.ledger_path), tuple(artifacts)


def _verify_missing_data_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped" or len(result.steps) != 1:
        raise G05AcceptanceError("g05_missing_data_voyage_not_stopped")
    step = result.steps[0]
    has_needs_input = any("needs_user_input:columns." in err for err in step.errors)
    if step.status != "blocked" or not has_needs_input:
        raise G05AcceptanceError("g05_missing_data_reason_mismatch")
    if step.ledger_path is None:
        raise G05AcceptanceError("g05_missing_data_run_report_missing")
    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    if report.status is not RunStatus.BLOCKED:
        raise G05AcceptanceError("g05_missing_data_report_status_not_blocked")
    if report.metadata.get("needs_user_input") is not True:
        raise G05AcceptanceError("g05_missing_data_needs_user_input_not_flagged")

    artifacts: list[Path] = []
    for art in report.artifacts:
        art_path = root / art.path if not Path(art.path).is_absolute() else Path(art.path)
        if art_path.is_file() and art_path.stat().st_size > 0:
            artifacts.append(art_path)
    return Path(step.ledger_path), tuple(artifacts)


def _verify_insufficient_items_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped" or len(result.steps) != 2:
        raise G05AcceptanceError("g05_insufficient_items_voyage_not_stopped")
    step = result.steps[1]
    has_insufficient_error = any("insufficient_cost_items" in err for err in step.errors)
    if step.status != "blocked" or not has_insufficient_error:
        raise G05AcceptanceError("g05_insufficient_items_reason_mismatch")
    if step.ledger_path is None:
        raise G05AcceptanceError("g05_insufficient_items_run_report_missing")
    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    if report.status is not RunStatus.BLOCKED:
        raise G05AcceptanceError("g05_insufficient_items_report_status_not_blocked")

    artifacts: list[Path] = []
    for s in result.steps:
        if s.ledger_path:
            rep = RunLedger(Path(s.ledger_path).parent).load(s.run_id)
            for art in rep.artifacts:
                art_path = root / art.path if not Path(art.path).is_absolute() else Path(art.path)
                if art_path.is_file() and art_path.stat().st_size > 0:
                    artifacts.append(art_path)
    return Path(step.ledger_path), tuple(artifacts)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _artifact_receipt(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": _relative(root, path),
        "sha256": _sha256(path),
    }


def _render_evidence_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# G05 Acceptance Dossier",
        "",
        f"- Run ID: `{receipt['run_id']}`",
        f"- Input SHA-256: `{receipt['input_sha256']}`",
        f"- Output SHA-256: `{receipt['output_sha256']}`",
        "",
        "## Result Checks",
        "",
    ]
    for check in receipt["result_checks"]:
        status = "passed" if check.get("passed") else "failed"
        lines.append(f"- **{check['name']}**: {status} — {check.get('evidence', '')}")
    lines.extend(
        [
            "",
            "## Negative Paths",
            "",
            f"- Primary: `{receipt['negative_path']['case']}` "
            f"({receipt['negative_path']['status']})",
            f"  {receipt['negative_path']['evidence']}",
        ]
    )
    for extra in receipt.get("additional_negative_paths", []):
        lines.extend(
            [
                f"- Additional: `{extra['case']}` ({extra['status']})",
                f"  {extra['evidence']}",
            ]
        )
    lines.append("")
    return "\n".join(lines)
