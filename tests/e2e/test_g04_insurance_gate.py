from __future__ import annotations

import json
from pathlib import Path

from nemofold.application import ExecutionConfig
from nemofold.contracts import RunStatus
from nemofold.ledger import RunLedger
from nemofold.voyage_runs import run_voyage

POLICY_HAFTPFLICHT = """Versicherungsschein
Versicherungsnehmer: Alex Beispiel
Police: HP-2024-8819
Tarif: Privat-Haftpflicht Basis
Deckung ab: 01.01.2024
Deckung bis: 31.12.2026
Abdeckung: Personen- und Sachschäden bis 10 Mio EUR
Kosten: 72,00 EUR pro Jahr
Turnus: jährlich
Kontakt: service@haftpflicht-direkt.de
"""

POLICY_HAUSRAT = """Versicherungsschein
Versicherungsnehmer: Alex Beispiel
Police: HR-2023-4102
Tarif: Hausrat Premium
Deckung ab: 15.03.2023
Deckung bis: unbestimmt
Abdeckung: Feuer, Leitungswasser, Sturm, Hagel, Einbruchdiebstahl
Kosten: 144,00 EUR pro Jahr
Turnus: jährlich
Kontakt: info@hausrat-schadenservice.de
"""

POLICY_AUSLANDSKRANKEN = """Versicherungsschein
Versicherungsnehmer: Alex Beispiel
Police: AKV-2025-0091
Tarif: Auslandskranken Schutz
Deckung ab: 01.06.2025
Deckung bis: 31.05.2026
Abdeckung: Notfall-Heilbehandlung im Ausland weltweit
Kosten: 36,00 EUR pro Jahr
Turnus: jährlich
Kontakt: hilfe@weltweit-notfall.de
"""


def _setup_positive_policies(root: Path) -> Path:
    policies_dir = root / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "01-privathaftpflicht.txt").write_text(POLICY_HAFTPFLICHT, encoding="utf-8")
    (policies_dir / "02-hausrat.txt").write_text(POLICY_HAUSRAT, encoding="utf-8")
    (policies_dir / "03-auslandskranken.txt").write_text(POLICY_AUSLANDSKRANKEN, encoding="utf-8")
    return policies_dir


def test_g04_positive_voyage_extracts_policies_timeline_and_digest(tmp_path: Path) -> None:
    policies = _setup_positive_policies(tmp_path)
    out_dir = tmp_path / "out"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))

    voyage = {
        "voyage_id": "voyage_g04_full_insurance_chain",
        "name": "Versicherungen erfassen, normalisieren und analysieren",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(policies)],
                    "output_dir": str(out_dir / "01_registry"),
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
                    "input_roots": [str(policies)],
                    "output_dir": str(out_dir / "02_timeline"),
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
                    "input_roots": [str(policies)],
                    "output_dir": str(out_dir / "03_digest"),
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

    result = run_voyage(
        voyage,
        config,
        run_id="run_g04_positive_chain",
        base_dir=tmp_path,
    )

    assert result.status == "executed"
    assert result.completed is True
    assert len(result.steps) == 3

    # Check Step 1 Registry Table
    step1 = result.steps[0]
    assert step1.status == "executed"
    reg_json = Path(step1.output_dir) / f"{step1.run_id}.registry.json"
    assert reg_json.is_file()
    reg_data = json.loads(reg_json.read_text(encoding="utf-8"))
    assert len(reg_data["rows"]) == 3
    assert reg_data["filled_cells"] == 15
    assert reg_data["empty_cells"] == 0

    # Check Step 2 Timeline & Open End Note
    step2 = result.steps[1]
    assert step2.status == "executed"
    time_json = Path(step2.output_dir) / f"{step2.run_id}.timeline.json"
    assert time_json.is_file()
    time_data = json.loads(time_json.read_text(encoding="utf-8"))
    assert time_data["event_count"] == 3
    assert time_data["undetermined_count"] == 0
    # Check open end on Hausrat
    events_by_label = {e["label"]: e for e in time_data["events"]}
    assert events_by_label["Hausrat Premium"]["end"] is None
    assert events_by_label["Privat-Haftpflicht Basis"]["end"] == "2026-12-31"

    # Check Step 3 Digest with disclaimer and verified handoff
    step3 = result.steps[2]
    assert step3.status == "executed"
    assert step3.handoff is not None
    assert step3.handoff["status"] == "verified"
    assert step3.handoff["producer_run_id"] == step2.run_id
    assert step3.handoff["producer_workflow"] == "coverage_timeline"
    assert step3.handoff["format"] == "markdown"

    digest_md = Path(step3.output_dir) / f"{step3.run_id}.digest.md"
    digest_text = digest_md.read_text(encoding="utf-8")
    assert "Nutzungsgrenze" in digest_text
    assert "§ 34d/e GewO" in digest_text
    assert "Versicherungsverlauf" in digest_text


def test_g04_missing_coverage_dates_blocks_without_inventing_coverage(tmp_path: Path) -> None:
    doc_dir = tmp_path / "vage_doc"
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "unfall.txt").write_text(
        "Versicherungsschein\n"
        "Versicherungsnehmer: Alex Beispiel\n"
        "Police: UV-991\n"
        "Tarif: Unfall Kompakt\n"
        "Deckung ab: unbestimmt\n"
        "Deckung bis: unklar\n"
        "Abdeckung: Vollinvalidität\n"
        "Kosten: 50,00 EUR\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out_vage"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))

    voyage = {
        "voyage_id": "voyage_missing_dates",
        "name": "Versicherungsverlauf · fehlende Deckungsdaten",
        "steps": [
            {
                "workflow": "coverage_timeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "coverage_timeline",
                    "input_roots": [str(doc_dir)],
                    "output_dir": str(out_dir),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "min_intervals": 1,
                    },
                },
            }
        ],
    }

    result = run_voyage(
        voyage,
        config,
        run_id="run_missing_dates",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert result.stopped_at == 1
    step = result.steps[0]
    assert step.status == "blocked"
    assert step.errors == ("insufficient_coverage_intervals:0<1",)

    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    assert report.status is RunStatus.BLOCKED
    assert report.metadata["needs_user_input"] is True
    assert report.metadata["undetermined_count"] == 1

    needs_artifact = next(
        Path(item.path) for item in report.artifacts if item.format == "needs-user-input"
    )
    assert needs_artifact.is_file()
    q_data = json.loads(needs_artifact.read_text(encoding="utf-8"))
    assert q_data["questions"][0]["field"] == "coverage_dates"


def test_g04_missing_required_contract_columns_blocks_registry(tmp_path: Path) -> None:
    doc_dir = tmp_path / "incomplete_doc"
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "haftpflicht.txt").write_text(
        "Versicherungsschein\n"
        "Versicherungsnehmer: Alex Beispiel\n"
        "Tarif: Privat-Haftpflicht Basis\n"
        "Deckung ab: 01.01.2024\n"
        "Deckung bis: 31.12.2026\n"
        "Kosten: 72,00 EUR pro Jahr\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out_incomplete"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))

    voyage = {
        "voyage_id": "voyage_missing_columns",
        "name": "Policen-Inventar · fehlende Pflichtdaten",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(doc_dir)],
                    "output_dir": str(out_dir),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "insurance_registry",
                        "required_columns": ["Police", "Tarif", "Abdeckung", "Kosten"],
                    },
                },
            }
        ],
    }

    result = run_voyage(
        voyage,
        config,
        run_id="run_missing_columns",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert result.stopped_at == 1
    step = result.steps[0]
    assert step.status == "blocked"
    assert any("needs_user_input:columns." in err for err in step.errors)

    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    assert report.status is RunStatus.BLOCKED
    assert report.metadata["needs_user_input"] is True


def test_g04_unauthorized_broker_advice_is_denied(tmp_path: Path) -> None:
    doc_dir = tmp_path / "policies"
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "01-haftpflicht.txt").write_text(POLICY_HAFTPFLICHT, encoding="utf-8")
    out_dir = tmp_path / "out_unauthorized"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))

    voyage = {
        "voyage_id": "voyage_unauthorized_advice",
        "name": "Versicherungsberatung · unautorisierte Maklerempfehlung",
        "steps": [
            {
                "workflow": "folder_digest",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(doc_dir)],
                    "output_dir": str(out_dir),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "application_domain": "insurance",
                        "insurance_purpose": "broker_recommendation",
                    },
                },
            }
        ],
    }

    result = run_voyage(
        voyage,
        config,
        run_id="run_unauthorized_advice",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert result.stopped_at == 1
    step = result.steps[0]
    assert step.status == "blocked"
    assert step.errors == ("insurance_authority_denied:broker_recommendation",)

    report = RunLedger(Path(step.ledger_path).parent).load(step.run_id)
    assert report.status is RunStatus.BLOCKED
    assert report.metadata["insurance_authority"] == "denied"
    assert report.metadata["needs_user_input"] is True

    needs_artifact = next(
        Path(item.path) for item in report.artifacts if item.format == "needs-user-input"
    )
    assert needs_artifact.is_file()
    q_data = json.loads(needs_artifact.read_text(encoding="utf-8"))
    assert q_data["questions"][0]["field"] == "insurance_purpose"
