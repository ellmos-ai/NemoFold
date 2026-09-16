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


class G04AcceptanceError(RuntimeError):
    """Raised when the executable G04 acceptance chain does not meet its contract."""


@dataclass(frozen=True, slots=True)
class G04AcceptanceBundle:
    root: Path
    register_path: Path
    positive_dossier_path: Path
    missing_dates_dossier_path: Path
    missing_data_dossier_path: Path
    unauthorized_advice_dossier_path: Path
    verification: dict[str, Any]


def run_g04_acceptance_bundle(
    output_root: str | Path,
) -> G04AcceptanceBundle:
    """Run the synthetic G04 positive and blocking paths and seal their evidence."""
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G04AcceptanceError(f"g04_evidence_root_not_empty:{root}")
    root.mkdir(parents=True, exist_ok=True)
    positive_inputs = _write_positive_fixture(root)
    missing_dates_input = _write_missing_dates_fixture(root)
    missing_data_input = _write_missing_data_fixture(root)
    unauthorized_advice_input = _write_unauthorized_advice_fixture(root)
    config = ExecutionConfig(allowed_roots=(str(root),))

    positive = _run_positive_voyage(root, positive_inputs[0].parent, config)
    missing_dates = _run_missing_dates_voyage(root, missing_dates_input.parent, config)
    missing_data = _run_missing_data_voyage(root, missing_data_input.parent, config)
    unauthorized_advice = _run_unauthorized_advice_voyage(
        root, unauthorized_advice_input.parent, config
    )

    positive_report, output_artifacts = _verify_positive_result(root, positive)
    missing_dates_report, missing_dates_artifacts = _verify_missing_dates_result(
        root, missing_dates
    )
    missing_data_report, missing_data_artifacts = _verify_missing_data_result(
        root, missing_data
    )
    unauthorized_advice_report, unauthorized_advice_artifacts = (
        _verify_unauthorized_advice_result(root, unauthorized_advice)
    )

    handoff_path = root / "evidence" / "g04-handoff.json"
    handoff = positive.steps[-1].handoff
    if not isinstance(handoff, dict):
        raise G04AcceptanceError("g04_positive_handoff_missing")
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
            unauthorized_advice_input,
        )
    ]
    dossier_artifacts = (
        Path(positive.dossier_path),
        Path(positive.dossier_path).with_suffix(".md"),
        Path(missing_dates.dossier_path),
        Path(missing_dates.dossier_path).with_suffix(".md"),
        Path(missing_data.dossier_path),
        Path(missing_data.dossier_path).with_suffix(".md"),
        Path(unauthorized_advice.dossier_path),
        Path(unauthorized_advice.dossier_path).with_suffix(".md"),
    )
    output_receipts = [
        _artifact_receipt(root, path)
        for path in (
            *output_artifacts,
            *missing_dates_artifacts,
            *missing_data_artifacts,
            *unauthorized_advice_artifacts,
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
                "producer": "coverage_timeline",
                "consumer": "folder_digest",
                "artifact_path": _relative(root, handoff_path),
                "artifact_sha256": _sha256(handoff_path),
                "status": "verified",
                "evidence": (
                    "Der verifizierte Deckungsbericht wurde hashgebunden an den "
                    "Digest zur Bestands- und Beratungsauswertung übergeben."
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
                "name": "policy_inventory_and_normalization",
                "passed": True,
                "evidence": (
                    "Policen, Tarife, Abdeckung, Kosten und Kontakte wurden deterministisch "
                    "extrahiert, normalisiert und mit Zeilenankern belegt."
                ),
            },
            {
                "name": "objective_coverage_timeline_analysis",
                "passed": True,
                "evidence": (
                    "Deckungszeiträume und offene Vertragsenden wurden ohne erfundene "
                    "Deckung tagesgenau analysiert und visualisiert."
                ),
            },
            {
                "name": "bounded_advisory_handoff_with_disclaimer",
                "passed": True,
                "evidence": (
                    "Die Beratungsauswertung übernahm ausschließlich belegte Deckungsfakten "
                    "und trägt den gesetzlichen Nichtberatungshinweis (§ 34d/e GewO)."
                ),
            },
        ],
        "negative_path": {
            "case": "missing_contract_coverage_dates",
            "run_id": missing_dates.steps[0].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "evidence": (
                "Fehlende oder unlesbare Deckungsdaten stoppten die Zeitachse vor "
                "der Weitergabe und erzeugten Unsicherheitshinweise."
            ),
            "run_report": {
                "path": _relative(root, missing_dates_report),
                "sha256": _sha256(missing_dates_report),
            },
        },
        "additional_negative_paths": [
            {
                "case": "missing_required_contract_data",
                "run_id": missing_data.steps[0].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "evidence": (
                    "Fehlende Pflichtspalten im Policen-Register blockierten vor "
                    "der Weitergabe mit einer strukturierten Rückfrage."
                ),
                "run_report": {
                    "path": _relative(root, missing_data_report),
                    "sha256": _sha256(missing_data_report),
                },
            },
            {
                "case": "unauthorized_broker_advice",
                "run_id": unauthorized_advice.steps[0].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "evidence": (
                    "Angeforderte Vermittler- oder verbindliche Deckungsempfehlungen "
                    "wurden mangels Maklerautorität (§ 34d GewO) abgewiesen."
                ),
                "run_report": {
                    "path": _relative(root, unauthorized_advice_report),
                    "sha256": _sha256(unauthorized_advice_report),
                },
            },
        ],
    }

    register = load_gate_register()
    gate = next(item for item in register["gates"] if item["gate_id"] == "G04")
    gate["status"] = "partial"
    gate["evidence"] = {
        "test_nodes": [],
        "run_receipts": [receipt],
    }
    verification = verify_gate_evidence(register, root)
    register_path = root / "gate-register.g04.json"
    write_text_artifact(
        register_path,
        json.dumps(register, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )
    return G04AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(positive.dossier_path),
        missing_dates_dossier_path=Path(missing_dates.dossier_path),
        missing_data_dossier_path=Path(missing_data.dossier_path),
        unauthorized_advice_dossier_path=Path(unauthorized_advice.dossier_path),
        verification=verification,
    )


def _write_positive_fixture(root: Path) -> tuple[Path, Path, Path]:
    policies = root / "positive" / "inputs" / "insurance-policies"
    policies.mkdir(parents=True, exist_ok=True)
    haftpflicht = policies / "01-privathaftpflicht.txt"
    haftpflicht.write_text(
        "Versicherungsschein\n"
        "Versicherungsnehmer: Alex Beispiel\n"
        "Police: HP-2024-8819\n"
        "Tarif: Privat-Haftpflicht Basis\n"
        "Deckung ab: 01.01.2024\n"
        "Deckung bis: 31.12.2026\n"
        "Abdeckung: Personen- und Sachschäden bis 10 Mio EUR\n"
        "Kosten: 72,00 EUR pro Jahr\n"
        "Turnus: jährlich\n"
        "Kontakt: service@haftpflicht-direkt.de\n",
        encoding="utf-8",
    )
    hausrat = policies / "02-hausrat.txt"
    hausrat.write_text(
        "Versicherungsschein\n"
        "Versicherungsnehmer: Alex Beispiel\n"
        "Police: HR-2023-4102\n"
        "Tarif: Hausrat Premium\n"
        "Deckung ab: 15.03.2023\n"
        "Deckung bis: unbestimmt\n"
        "Abdeckung: Feuer, Leitungswasser, Sturm, Hagel, Einbruchdiebstahl\n"
        "Kosten: 144,00 EUR pro Jahr\n"
        "Turnus: jährlich\n"
        "Kontakt: info@hausrat-schadenservice.de\n",
        encoding="utf-8",
    )
    auslandskranken = policies / "03-auslandskranken.txt"
    auslandskranken.write_text(
        "Versicherungsschein\n"
        "Versicherungsnehmer: Alex Beispiel\n"
        "Police: AKV-2025-0091\n"
        "Tarif: Auslandskranken Schutz\n"
        "Deckung ab: 01.06.2025\n"
        "Deckung bis: 31.05.2026\n"
        "Abdeckung: Notfall-Heilbehandlung im Ausland weltweit\n"
        "Kosten: 36,00 EUR pro Jahr\n"
        "Turnus: jährlich\n"
        "Kontakt: hilfe@weltweit-notfall.de\n",
        encoding="utf-8",
    )
    return haftpflicht, hausrat, auslandskranken


def _write_missing_dates_fixture(root: Path) -> Path:
    policies = root / "missing-dates-negative" / "inputs" / "insurance-policies"
    policies.mkdir(parents=True, exist_ok=True)
    unfall = policies / "01-unfall-ohne-deckung.txt"
    unfall.write_text(
        "Versicherungsschein\n"
        "Versicherungsnehmer: Alex Beispiel\n"
        "Police: UV-2025-9981\n"
        "Tarif: Unfall-Kompakt\n"
        "Deckung ab: unbestimmt\n"
        "Deckung bis: unklar\n"
        "Abdeckung: Invaliditätsleistung bei Vollinvalidität\n"
        "Kosten: 60,00 EUR pro Jahr\n"
        "Turnus: jährlich\n"
        "Kontakt: service@unfall-direkt.de\n",
        encoding="utf-8",
    )
    return unfall


def _write_missing_data_fixture(root: Path) -> Path:
    policies = root / "missing-data-negative" / "inputs" / "insurance-policies"
    policies.mkdir(parents=True, exist_ok=True)
    unvollstaendig = policies / "01-haftpflicht-unvollstaendig.txt"
    unvollstaendig.write_text(
        "Versicherungsschein\n"
        "Versicherungsnehmer: Alex Beispiel\n"
        "Tarif: Privat-Haftpflicht Basis\n"
        "Deckung ab: 01.01.2024\n"
        "Deckung bis: 31.12.2026\n"
        "Kosten: 72,00 EUR pro Jahr\n"
        "Kontakt: service@haftpflicht-direkt.de\n",
        encoding="utf-8",
    )
    return unvollstaendig


def _write_unauthorized_advice_fixture(root: Path) -> Path:
    policies = root / "unauthorized-advice-negative" / "inputs" / "insurance-policies"
    policies.mkdir(parents=True, exist_ok=True)
    haftpflicht = policies / "01-privathaftpflicht.txt"
    haftpflicht.write_text(
        "Versicherungsschein\n"
        "Versicherungsnehmer: Alex Beispiel\n"
        "Police: HP-2024-8819\n"
        "Tarif: Privat-Haftpflicht Basis\n"
        "Deckung ab: 01.01.2024\n"
        "Deckung bis: 31.12.2026\n"
        "Abdeckung: Personen- und Sachschäden bis 10 Mio EUR\n"
        "Kosten: 72,00 EUR pro Jahr\n"
        "Turnus: jährlich\n"
        "Kontakt: service@haftpflicht-direkt.de\n",
        encoding="utf-8",
    )
    return haftpflicht


def _run_positive_voyage(
    root: Path,
    records: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    case = _g04_positive_case(
        records,
        root / "positive" / "out",
        voyage_id="voyage_g04_acceptance_positive",
        title="Versicherungen erfassen, normalisieren und analysieren",
    )
    return run_voyage(
        case,
        config,
        run_id="g04_acceptance_positive",
        base_dir=root,
    )


def _run_missing_dates_voyage(
    root: Path,
    records: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    case = {
        "voyage_id": "voyage_g04_missing_dates",
        "name": "Versicherungsverlauf · fehlende Deckungsdaten",
        "steps": [
            {
                "workflow": "coverage_timeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "coverage_timeline",
                    "input_roots": [str(records)],
                    "output_dir": str(root / "missing-dates-negative" / "out" / "timeline"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "start_field": "Deckung ab",
                        "end_field": "Deckung bis",
                        "label_field": "Tarif",
                        "holder_field": "Versicherungsnehmer",
                        "min_intervals": 1,
                        "title": "Versicherungsverlauf",
                        "formats": ["md"],
                    },
                },
            }
        ],
    }
    return run_voyage(
        case,
        config,
        run_id="g04_acceptance_missing_dates",
        base_dir=root,
    )


def _run_missing_data_voyage(
    root: Path,
    records: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    case = {
        "voyage_id": "voyage_g04_missing_data",
        "name": "Policen-Inventar · fehlende Pflichtdaten",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(records)],
                    "output_dir": str(root / "missing-data-negative" / "out" / "registry"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "insurance_registry",
                        "required_columns": ["Police", "Tarif", "Abdeckung", "Kosten"],
                        "formats": ["md"],
                    },
                },
            }
        ],
    }
    return run_voyage(
        case,
        config,
        run_id="g04_acceptance_missing_data",
        base_dir=root,
    )


def _run_unauthorized_advice_voyage(
    root: Path,
    records: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    case = {
        "voyage_id": "voyage_g04_unauthorized_advice",
        "name": "Versicherungsberatung · unautorisierte Vermittlerempfehlung",
        "steps": [
            {
                "workflow": "folder_digest",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(records)],
                    "output_dir": str(root / "unauthorized-advice-negative" / "out" / "digest"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "summary_length": 3,
                        "digest_depth": "full",
                        "application_domain": "insurance",
                        "insurance_purpose": "broker_recommendation",
                    },
                },
            }
        ],
    }
    return run_voyage(
        case,
        config,
        run_id="g04_acceptance_unauthorized_advice",
        base_dir=root,
    )


def _g04_positive_case(
    records: Path,
    output_root: Path,
    *,
    voyage_id: str,
    title: str,
) -> dict[str, Any]:
    return {
        "voyage_id": voyage_id,
        "name": title,
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(records)],
                    "output_dir": str(output_root / "registry"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "insurance_registry",
                        "required_columns": ["Police", "Tarif", "Abdeckung", "Kosten"],
                        "formats": ["md"],
                    },
                },
            },
            {
                "workflow": "coverage_timeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "coverage_timeline",
                    "input_roots": [str(records)],
                    "output_dir": str(output_root / "timeline"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "start_field": "Deckung ab",
                        "end_field": "Deckung bis",
                        "label_field": "Tarif",
                        "holder_field": "Versicherungsnehmer",
                        "min_intervals": 3,
                        "title": "Versicherungsverlauf & Abdeckungsanalyse",
                        "formats": ["md"],
                    },
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
                        "application_domain": "insurance",
                        "insurance_purpose": "coverage_analysis",
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
    if result.status != "executed" or len(result.steps) != 3:
        raise G04AcceptanceError("g04_positive_voyage_not_executed")
    handoff = result.steps[-1].handoff or {}
    if handoff.get("status") != "verified":
        raise G04AcceptanceError("g04_positive_handoff_not_verified")
    if handoff.get("producer_workflow") != "coverage_timeline":
        raise G04AcceptanceError("g04_positive_producer_workflow_mismatch")
    if handoff.get("format") != "markdown":
        raise G04AcceptanceError("g04_positive_handoff_format_mismatch")

    # Step 1: Document Registry verification
    step1 = result.steps[0]
    reg_out = Path(step1.output_dir)
    reg_json = reg_out / f"{step1.run_id}.registry.json"
    reg_csv = reg_out / f"{step1.run_id}.registry.csv"
    reg_md = reg_out / f"{step1.run_id}_registry.md"
    job1 = reg_out / "jobs" / f"{step1.run_id}.json"
    for p in (reg_json, reg_csv, reg_md, job1):
        if not p.is_file():
            raise G04AcceptanceError(f"g04_step1_artifact_missing:{p.name}")
    reg_data = json.loads(reg_json.read_text(encoding="utf-8"))
    if len(reg_data.get("rows", [])) != 3:
        raise G04AcceptanceError("g04_registry_row_count_mismatch")
    if reg_data.get("filled_cells") != 15 or reg_data.get("empty_cells") != 0:
        raise G04AcceptanceError("g04_registry_cells_mismatch")

    # Step 2: Coverage Timeline verification
    step2 = result.steps[1]
    time_out = Path(step2.output_dir)
    time_json = time_out / f"{step2.run_id}.timeline.json"
    time_svg = time_out / f"{step2.run_id}.timeline.svg"
    time_md = time_out / f"{step2.run_id}_coverage.md"
    job2 = time_out / "jobs" / f"{step2.run_id}.json"
    for p in (time_json, time_svg, time_md, job2):
        if not p.is_file():
            raise G04AcceptanceError(f"g04_step2_artifact_missing:{p.name}")
    time_data = json.loads(time_json.read_text(encoding="utf-8"))
    if time_data.get("event_count") != 3:
        raise G04AcceptanceError("g04_timeline_event_count_mismatch")
    if time_data.get("undetermined_count") != 0:
        raise G04AcceptanceError("g04_timeline_undetermined_mismatch")

    # Step 3: Digest & Advisory verification
    step3 = result.steps[2]
    dig_out = Path(step3.output_dir)
    dig_md = dig_out / f"{step3.run_id}.digest.md"
    job3 = dig_out / "jobs" / f"{step3.run_id}.json"
    for p in (dig_md, job3):
        if not p.is_file():
            raise G04AcceptanceError(f"g04_step3_artifact_missing:{p.name}")
    digest_text = dig_md.read_text(encoding="utf-8")
    if "Nutzungsgrenze" not in digest_text or "§ 34d/e GewO" not in digest_text:
        raise G04AcceptanceError("g04_digest_disclaimer_missing")

    consumer_report_path = step3.ledger_path
    if consumer_report_path is None:
        raise G04AcceptanceError("g04_positive_consumer_report_missing")
    consumer_report = RunLedger(Path(consumer_report_path).parent).load(step3.run_id)
    if consumer_report.status is not RunStatus.EXECUTED:
        raise G04AcceptanceError("g04_positive_consumer_not_executed")

    return Path(consumer_report_path), (
        reg_json,
        reg_csv,
        reg_md,
        job1,
        time_json,
        time_svg,
        time_md,
        job2,
        dig_md,
        job3,
    )


def _verify_missing_dates_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped" or len(result.steps) != 1:
        raise G04AcceptanceError("g04_missing_dates_voyage_not_stopped")
    step = result.steps[0]
    if step.status != "blocked" or step.errors != ("insufficient_coverage_intervals:0<1",):
        raise G04AcceptanceError("g04_missing_dates_reason_mismatch")
    if step.ledger_path is None:
        raise G04AcceptanceError("g04_missing_dates_run_report_missing")
    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    if report.status is not RunStatus.BLOCKED:
        raise G04AcceptanceError("g04_missing_dates_report_status_not_blocked")
    if report.metadata.get("needs_user_input") is not True:
        raise G04AcceptanceError("g04_missing_dates_metadata_needs_user_input_missing")

    needs_artifact = next(
        (Path(item.path) for item in report.artifacts if item.format == "needs-user-input"),
        None,
    )
    if needs_artifact is None or not needs_artifact.is_file():
        raise G04AcceptanceError("g04_missing_dates_needs_input_artifact_missing")
    question_data = json.loads(needs_artifact.read_text(encoding="utf-8"))
    questions = question_data.get("questions", [])
    if not questions or questions[0].get("field") != "coverage_dates":
        raise G04AcceptanceError("g04_missing_dates_question_field_mismatch")

    job_snapshot = Path(step.output_dir) / "jobs" / f"{step.run_id}.json"
    artifacts = [needs_artifact]
    if job_snapshot.is_file():
        artifacts.append(job_snapshot)
    return Path(step.ledger_path), tuple(artifacts)


def _verify_missing_data_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped" or len(result.steps) != 1:
        raise G04AcceptanceError("g04_missing_data_voyage_not_stopped")
    step = result.steps[0]
    has_needs_input = any("needs_user_input:columns." in err for err in step.errors)
    if step.status != "blocked" or not has_needs_input:
        raise G04AcceptanceError("g04_missing_data_reason_mismatch")
    if step.ledger_path is None:
        raise G04AcceptanceError("g04_missing_data_run_report_missing")
    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    if report.status is not RunStatus.BLOCKED:
        raise G04AcceptanceError("g04_missing_data_report_status_not_blocked")
    if report.metadata.get("needs_user_input") is not True:
        raise G04AcceptanceError("g04_missing_data_metadata_needs_user_input_missing")

    needs_artifact = next(
        (Path(item.path) for item in report.artifacts if item.format == "needs-user-input"),
        None,
    )
    if needs_artifact is None or not needs_artifact.is_file():
        raise G04AcceptanceError("g04_missing_data_needs_input_artifact_missing")

    job_snapshot = Path(step.output_dir) / "jobs" / f"{step.run_id}.json"
    artifacts = [needs_artifact]
    if job_snapshot.is_file():
        artifacts.append(job_snapshot)
    return Path(step.ledger_path), tuple(artifacts)


def _verify_unauthorized_advice_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped" or len(result.steps) != 1:
        raise G04AcceptanceError("g04_unauthorized_advice_voyage_not_stopped")
    step = result.steps[0]
    if step.status != "blocked" or step.errors != (
        "insurance_authority_denied:broker_recommendation",
    ):
        raise G04AcceptanceError("g04_unauthorized_advice_reason_mismatch")
    if step.ledger_path is None:
        raise G04AcceptanceError("g04_unauthorized_advice_run_report_missing")
    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    if report.status is not RunStatus.BLOCKED:
        raise G04AcceptanceError("g04_unauthorized_advice_report_status_not_blocked")
    if report.metadata.get("needs_user_input") is not True:
        raise G04AcceptanceError("g04_unauthorized_advice_metadata_needs_user_input_missing")

    needs_artifact = next(
        (Path(item.path) for item in report.artifacts if item.format == "needs-user-input"),
        None,
    )
    if needs_artifact is None or not needs_artifact.is_file():
        raise G04AcceptanceError("g04_unauthorized_advice_needs_input_artifact_missing")
    question_data = json.loads(needs_artifact.read_text(encoding="utf-8"))
    questions = question_data.get("questions", [])
    if not questions or questions[0].get("field") != "insurance_purpose":
        raise G04AcceptanceError("g04_unauthorized_advice_question_field_mismatch")

    job_snapshot = Path(step.output_dir) / "jobs" / f"{step.run_id}.json"
    artifacts = [needs_artifact]
    if job_snapshot.is_file():
        artifacts.append(job_snapshot)
    return Path(step.ledger_path), tuple(artifacts)


def _artifact_receipt(root: Path, path: Path) -> dict[str, str]:
    return {"path": _relative(root, path), "sha256": _sha256(path)}


def _relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
