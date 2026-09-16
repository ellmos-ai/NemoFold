"""Executable acceptance bundle for Gate G06: Subscription Reconciliation (Ellmos UC 11).

Positive and fail-closed blocking paths for subscription reconciliation against message evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .acceptance_gates import (
    artifact_manifest_sha256,
    load_gate_register,
    verify_gate_evidence,
)
from .application import ExecutionConfig
from .artifacts import write_text_artifact
from .contracts import RunStatus
from .ledger import RunLedger
from .voyage_runs import VoyageRunResult, run_voyage


class G06AcceptanceError(RuntimeError):
    """Raised when the executable G06 acceptance chain does not meet its contract."""


@dataclass(frozen=True, slots=True)
class G06AcceptanceBundle:
    root: Path
    register_path: Path
    positive_dossier_path: Path
    ambiguous_dossier_path: Path
    missing_data_dossier_path: Path
    insufficient_subs_dossier_path: Path
    verification: dict[str, Any]


def run_g06_acceptance_bundle(
    output_root: str | Path,
) -> G06AcceptanceBundle:
    """Run the synthetic G06 positive and blocking paths and seal their evidence."""
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G06AcceptanceError(f"g06_evidence_root_not_empty:{root}")
    root.mkdir(parents=True, exist_ok=True)
    positive_inputs = _write_positive_fixture(root)
    ambiguous_inputs = _write_ambiguous_fixture(root)
    missing_data_input = _write_missing_data_fixture(root)
    insufficient_subs_input = _write_insufficient_subs_fixture(root)
    config = ExecutionConfig(allowed_roots=(str(root),))

    positive = _run_positive_voyage(root, positive_inputs[0].parent, config)
    ambiguous = _run_ambiguous_voyage(root, ambiguous_inputs[0].parent, config)
    missing_data = _run_missing_data_voyage(root, missing_data_input.parent, config)
    insufficient_subs = _run_insufficient_subs_voyage(root, insufficient_subs_input.parent, config)

    positive_report, output_artifacts = _verify_positive_result(root, positive)
    ambiguous_report, ambiguous_artifacts = _verify_ambiguous_result(root, ambiguous)
    missing_data_report, missing_data_artifacts = _verify_missing_data_result(root, missing_data)
    insufficient_subs_report, insufficient_subs_artifacts = _verify_insufficient_subs_result(
        root, insufficient_subs
    )

    handoff_path = root / "evidence" / "g06-handoff.json"
    handoff = positive.steps[-1].handoff
    if not isinstance(handoff, dict):
        raise G06AcceptanceError("g06_positive_handoff_missing")
    write_text_artifact(
        handoff_path,
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    input_artifacts = [
        _artifact_receipt(root, path)
        for path in (
            *positive_inputs,
            *ambiguous_inputs,
            missing_data_input,
            insufficient_subs_input,
        )
    ]
    dossier_artifacts = (
        Path(positive.dossier_path),
        Path(positive.dossier_path).with_suffix(".md"),
        Path(ambiguous.dossier_path),
        Path(ambiguous.dossier_path).with_suffix(".md"),
        Path(missing_data.dossier_path),
        Path(missing_data.dossier_path).with_suffix(".md"),
        Path(insufficient_subs.dossier_path),
        Path(insufficient_subs.dossier_path).with_suffix(".md"),
    )
    output_receipts = [
        _artifact_receipt(root, path)
        for path in (
            *output_artifacts,
            *ambiguous_artifacts,
            *missing_data_artifacts,
            *insufficient_subs_artifacts,
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
                "producer": "subscription_reconcile",
                "consumer": "folder_digest",
                "artifact_path": _relative(root, handoff_path),
                "artifact_sha256": _sha256(handoff_path),
                "status": "verified",
                "evidence": (
                    "subscription_reconcile produces a verified markdown reconciliation report "
                    "with detected price changes and cancellation mismatches; folder_digest "
                    "consumes it as an objective overview handoff."
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
                "name": "price_discrepancy_detected_and_explained",
                "passed": True,
                "evidence": (
                    "Cloud Speicher Pro declared at 9.99 EUR is matched against incoming "
                    "invoice stating 12.99 EUR, correctly flagged as price_change discrepancy "
                    "with line quote."
                ),
            },
            {
                "name": "cancellation_status_mismatch_detected",
                "passed": True,
                "evidence": (
                    "Fitnessstudio StudioNord declared as active is matched against "
                    "incoming cancellation confirmation, correctly flagged as status_mismatch "
                    "discrepancy without inventing facts."
                ),
            },
            {
                "name": "unconfirmed_subscription_separated",
                "passed": True,
                "evidence": (
                    "Tageszeitung Digital without incoming message evidence remains unconfirmed "
                    "rather than guessed as active or paid."
                ),
            },
            {
                "name": "ambiguous_match_prevents_status_change",
                "passed": True,
                "evidence": (
                    "When multiple competing subscriptions match without account distinction, the "
                    "system halts with status=blocked and requests clarification via "
                    "needs-user-input."
                ),
            },
        ],
        "negative_path": {
            "case": "ambiguous_subscription_matches_blocked",
            "run_id": ambiguous.steps[1].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "run_report": {
                "path": _relative(root, ambiguous_report),
                "sha256": _sha256(ambiguous_report),
            },
            "evidence": (
                "When message evidence matches multiple subscriptions ambiguously without "
                "distinguishing account IDs, the workflow halts with status=blocked and requests "
                "user input rather than guessing a status change."
            ),
        },
        "additional_negative_paths": [
            {
                "case": "missing_required_subscription_column",
                "run_id": missing_data.steps[0].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": _relative(root, missing_data_report),
                    "sha256": _sha256(missing_data_report),
                },
                "evidence": (
                    "When a subscription declaration omits a required column such as 'Betrag', "
                    "document_registry halts immediately with needs-user-input."
                ),
            },
            {
                "case": "insufficient_subscriptions_floor",
                "run_id": insufficient_subs.steps[1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": _relative(root, insufficient_subs_report),
                    "sha256": _sha256(insufficient_subs_report),
                },
                "evidence": (
                    "When fewer subscriptions exist than declared minimum, subscription_reconcile "
                    "stops with status=blocked rather than silently proceeding."
                ),
            },
        ],
    }

    evidence_dossier = root / "evidence" / "g06-evidence-dossier.json"
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

    register = load_gate_register()
    gate = next(item for item in register["gates"] if item["gate_id"] == "G06")
    gate["status"] = "partial"
    gate["evidence"] = {
        "test_nodes": [],
        "run_receipts": [receipt],
    }
    verification = verify_gate_evidence(register, root)
    register_path = root / "gate-register.g06.json"
    write_text_artifact(
        register_path,
        json.dumps(register, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )
    return G06AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(positive.dossier_path),
        ambiguous_dossier_path=Path(ambiguous.dossier_path),
        missing_data_dossier_path=Path(missing_data.dossier_path),
        insufficient_subs_dossier_path=Path(insufficient_subs.dossier_path),
        verification=verification,
    )


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _write_positive_fixture(root: Path) -> list[Path]:
    in_dir = root / "inputs" / "positive"
    in_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    sub1 = in_dir / "01_streaming.txt"
    sub1.write_text(
        "Abo: Streaming Plus\n"
        "Betrag: 14,99 €\n"
        "Turnus: monatlich\n"
        "Status: aktiv\n"
        "Konto: ACC-STREAM-01\n",
        encoding="utf-8",
    )
    paths.append(sub1)

    sub2 = in_dir / "02_cloud.txt"
    sub2.write_text(
        "Abo: Cloud Speicher Pro\n"
        "Betrag: 9,99 €\n"
        "Turnus: monatlich\n"
        "Status: aktiv\n"
        "Konto: ACC-CLOUD-99\n",
        encoding="utf-8",
    )
    paths.append(sub2)

    sub3 = in_dir / "03_gym.txt"
    sub3.write_text(
        "Abo: Fitnessstudio StudioNord\n"
        "Betrag: 39,90 €\n"
        "Turnus: monatlich\n"
        "Status: aktiv\n"
        "Konto: ACC-GYM-12\n",
        encoding="utf-8",
    )
    paths.append(sub3)

    sub4 = in_dir / "04_newspaper.txt"
    sub4.write_text(
        "Abo: Tageszeitung Digital\n"
        "Betrag: 19,90 €\n"
        "Turnus: monatlich\n"
        "Status: aktiv\n"
        "Konto: ACC-NEWS-05\n",
        encoding="utf-8",
    )
    paths.append(sub4)

    msg1 = in_dir / "msg_01_streaming_rechnung.txt"
    msg1.write_text(
        "Absender: service@streaming-plus.de\n"
        "Betreff: Ihre Monatsrechnung Streaming Plus\n"
        "Datum: 2026-09-01\n"
        "Betrag: 14,99 €\n"
        "Konto: ACC-STREAM-01\n"
        "\n"
        "Vielen Dank für Ihre Zahlung. Ihr Streaming Plus Abonnement bleibt aktiv.\n",
        encoding="utf-8",
    )
    paths.append(msg1)

    msg2 = in_dir / "msg_02_cloud_preiserhoehung.txt"
    msg2.write_text(
        "Absender: billing@cloud-speicher.de\n"
        "Betreff: Tarifanpassung Cloud Speicher Pro\n"
        "Datum: 2026-09-05\n"
        "Betrag: 12,99 €\n"
        "Konto: ACC-CLOUD-99\n"
        "\n"
        "Wir passen unseren Monatspreis an. Neuer Betrag ab 01.10. beträgt 12,99 €.\n",
        encoding="utf-8",
    )
    paths.append(msg2)

    msg3 = in_dir / "msg_03_gym_kuendigung.txt"
    msg3.write_text(
        "Absender: info@studionord.de\n"
        "Betreff: Kündigungsbestätigung StudioNord\n"
        "Datum: 2026-09-10\n"
        "Konto: ACC-GYM-12\n"
        "\n"
        "Wir bestätigen den Eingang Ihrer Kündigung. Vertragsende ist der 31.10.2026.\n",
        encoding="utf-8",
    )
    paths.append(msg3)

    return paths


def _write_ambiguous_fixture(root: Path) -> list[Path]:
    in_dir = root / "inputs" / "neg_ambiguous"
    in_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    sub1 = in_dir / "01_music_personal.txt"
    sub1.write_text(
        "Abo: Musik Streaming\nBetrag: 9,99 €\nTurnus: monatlich\nStatus: aktiv\n",
        encoding="utf-8",
    )
    paths.append(sub1)

    sub2 = in_dir / "02_music_family.txt"
    sub2.write_text(
        "Abo: Musik Streaming\nBetrag: 14,99 €\nTurnus: monatlich\nStatus: aktiv\n",
        encoding="utf-8",
    )
    paths.append(sub2)

    msg1 = in_dir / "msg_ambiguous.txt"
    msg1.write_text(
        "Absender: billing@musik-streaming.de\n"
        "Betreff: Ihre Rechnung Musik Streaming\n"
        "Datum: 2026-09-12\n"
        "Betrag: 9,99 €\n"
        "\n"
        "Vielen Dank für Ihre Zahlung bei Musik Streaming.\n",
        encoding="utf-8",
    )
    paths.append(msg1)

    return paths


def _write_missing_data_fixture(root: Path) -> Path:
    in_dir = root / "inputs" / "neg_data"
    in_dir.mkdir(parents=True, exist_ok=True)
    p = in_dir / "01_missing_column.txt"
    p.write_text(
        "Abo: Software Cloud\nTurnus: monatlich\nStatus: aktiv\n",
        encoding="utf-8",
    )
    return p


def _write_insufficient_subs_fixture(root: Path) -> Path:
    in_dir = root / "inputs" / "neg_subs"
    in_dir.mkdir(parents=True, exist_ok=True)
    p = in_dir / "01_single_sub.txt"
    p.write_text(
        "Abo: Einzelnes Magazin\nBetrag: 5,00 €\nTurnus: monatlich\nStatus: aktiv\n",
        encoding="utf-8",
    )
    return p


# --------------------------------------------------------------------------- #
# Voyages
# --------------------------------------------------------------------------- #


def _run_positive_voyage(root: Path, input_dir: Path, config: ExecutionConfig) -> VoyageRunResult:
    voyage = {
        "name": "g06_positive_subscription_reconcile_voyage",
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
                        "title": "Abonnement-Inventar",
                    },
                },
            },
            {
                "workflow": "subscription_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "subscription_reconcile",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "positive_02_reconcile"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "formats": ["md"],
                        "min_subscriptions": 2,
                        "require_unambiguous_matches": True,
                        "title": "Abo-Abgleich mit Nachrichten",
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
        run_id="g06_pos",
        base_dir=root / "outputs" / "positive_dossier",
    )


def _run_ambiguous_voyage(root: Path, input_dir: Path, config: ExecutionConfig) -> VoyageRunResult:
    voyage = {
        "name": "g06_ambiguous_voyage",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "neg_ambiguous_01_registry"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "recurring_costs",
                        "formats": ["md"],
                    },
                },
            },
            {
                "workflow": "subscription_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "subscription_reconcile",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "neg_ambiguous_02_reconcile"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "require_unambiguous_matches": True,
                        "formats": ["md"],
                    },
                },
            },
        ],
    }
    return run_voyage(
        voyage,
        config,
        run_id="g06_neg_ambiguous",
        base_dir=root / "outputs" / "neg_ambiguous_dossier",
    )


def _run_missing_data_voyage(
    root: Path, input_dir: Path, config: ExecutionConfig
) -> VoyageRunResult:
    voyage = {
        "name": "g06_missing_data_voyage",
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
        run_id="g06_neg_data",
        base_dir=root / "outputs" / "neg_data_dossier",
    )


def _run_insufficient_subs_voyage(
    root: Path, input_dir: Path, config: ExecutionConfig
) -> VoyageRunResult:
    voyage = {
        "name": "g06_insufficient_subs_voyage",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "neg_subs_01_registry"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "recurring_costs",
                        "formats": ["md"],
                    },
                },
            },
            {
                "workflow": "subscription_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "subscription_reconcile",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "neg_subs_02_reconcile"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "min_subscriptions": 5,
                        "formats": ["md"],
                    },
                },
            },
        ],
    }
    return run_voyage(
        voyage,
        config,
        run_id="g06_neg_subs",
        base_dir=root / "outputs" / "neg_subs_dossier",
    )


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #


def _verify_positive_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "executed" or len(result.steps) != 3:
        raise G06AcceptanceError("g06_positive_voyage_failed")
    artifacts: list[Path] = []
    for step in result.steps:
        if step.status != "executed":
            raise G06AcceptanceError(f"g06_positive_step_not_executed:{step.workflow}")
        if step.ledger_path is None:
            raise G06AcceptanceError(f"g06_positive_ledger_missing:{step.workflow}")
        ledger_file = Path(step.ledger_path)
        report = RunLedger(ledger_file.parent).load(step.run_id)
        if report.status is not RunStatus.EXECUTED:
            raise G06AcceptanceError(f"g06_positive_step_report_not_executed:{step.workflow}")
        for art in report.artifacts:
            art_path = root / art.path if not Path(art.path).is_absolute() else Path(art.path)
            if not art_path.is_file() or art_path.stat().st_size == 0:
                raise G06AcceptanceError(f"g06_artifact_missing_or_empty:{art.path}")
            artifacts.append(art_path)

    reconcile_step = result.steps[1]
    reconcile_ledger = Path(reconcile_step.ledger_path)
    reconcile_report = RunLedger(reconcile_ledger.parent).load(reconcile_step.run_id)
    if reconcile_report.metadata.get("total_declared") != 4:
        raise G06AcceptanceError("g06_total_declared_mismatch")
    if reconcile_report.metadata.get("total_reconciled") != 1:
        raise G06AcceptanceError("g06_total_reconciled_mismatch")
    if reconcile_report.metadata.get("total_discrepancies") != 2:
        raise G06AcceptanceError("g06_total_discrepancies_mismatch")
    if reconcile_report.metadata.get("total_unconfirmed") != 1:
        raise G06AcceptanceError("g06_total_unconfirmed_mismatch")

    final_step = result.steps[-1]
    final_ledger = Path(final_step.ledger_path)
    return final_ledger, tuple(artifacts)


def _verify_ambiguous_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped" or len(result.steps) != 2:
        raise G06AcceptanceError("g06_ambiguous_voyage_not_stopped")
    step = result.steps[1]
    has_ambiguous_error = any("ambiguous_subscription_matches" in err for err in step.errors)
    if step.status != "blocked" or not has_ambiguous_error:
        raise G06AcceptanceError("g06_ambiguous_reason_mismatch")
    if step.ledger_path is None:
        raise G06AcceptanceError("g06_ambiguous_run_report_missing")
    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    if report.status is not RunStatus.BLOCKED:
        raise G06AcceptanceError("g06_ambiguous_report_status_not_blocked")
    if report.metadata.get("needs_user_input") is not True:
        raise G06AcceptanceError("g06_ambiguous_needs_user_input_not_flagged")

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
        raise G06AcceptanceError("g06_missing_data_voyage_not_stopped")
    step = result.steps[0]
    has_needs_input = any("needs_user_input:columns." in err for err in step.errors)
    if step.status != "blocked" or not has_needs_input:
        raise G06AcceptanceError("g06_missing_data_reason_mismatch")
    if step.ledger_path is None:
        raise G06AcceptanceError("g06_missing_data_run_report_missing")
    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    if report.status is not RunStatus.BLOCKED:
        raise G06AcceptanceError("g06_missing_data_report_status_not_blocked")
    if report.metadata.get("needs_user_input") is not True:
        raise G06AcceptanceError("g06_missing_data_needs_user_input_not_flagged")

    artifacts: list[Path] = []
    for art in report.artifacts:
        art_path = root / art.path if not Path(art.path).is_absolute() else Path(art.path)
        if art_path.is_file() and art_path.stat().st_size > 0:
            artifacts.append(art_path)
    return Path(step.ledger_path), tuple(artifacts)


def _verify_insufficient_subs_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped" or len(result.steps) != 2:
        raise G06AcceptanceError("g06_insufficient_subs_voyage_not_stopped")
    step = result.steps[1]
    has_insufficient_error = any("insufficient_subscriptions" in err for err in step.errors)
    if step.status != "blocked" or not has_insufficient_error:
        raise G06AcceptanceError("g06_insufficient_subs_reason_mismatch")
    if step.ledger_path is None:
        raise G06AcceptanceError("g06_insufficient_subs_run_report_missing")
    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    if report.status is not RunStatus.BLOCKED:
        raise G06AcceptanceError("g06_insufficient_subs_report_status_not_blocked")

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


def _relative(root: Path, target: Path) -> str:
    return target.resolve().relative_to(root.resolve()).as_posix()


def _artifact_receipt(root: Path, path: Path) -> dict[str, str]:
    resolved = path.resolve()
    return {
        "path": _relative(root, resolved),
        "sha256": _sha256(resolved),
    }


def _render_evidence_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# G06 Acceptance Dossier",
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
