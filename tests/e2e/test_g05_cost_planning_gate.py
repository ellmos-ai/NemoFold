from __future__ import annotations

import json
from pathlib import Path

from nemofold.application import ExecutionConfig
from nemofold.contracts import RunStatus
from nemofold.ledger import RunLedger
from nemofold.voyage_runs import run_voyage

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


def test_g05_positive_voyage_extracts_and_projects_costs(tmp_path: Path) -> None:
    inputs = tmp_path / "contracts"
    inputs.mkdir(parents=True)
    (inputs / "01_fitness.txt").write_text(CONTRACT_FITNESS, encoding="utf-8")
    (inputs / "02_streaming.txt").write_text(CONTRACT_STREAMING, encoding="utf-8")
    (inputs / "03_kfz_steuer.txt").write_text(CONTRACT_KFZ_STEUER, encoding="utf-8")
    (inputs / "04_tuev.txt").write_text(CONTRACT_TUEV, encoding="utf-8")
    (inputs / "05_rundfunk.txt").write_text(CONTRACT_RUNDFUNK, encoding="utf-8")

    voyage = {
        "name": "test_g05_positive_cost_planning",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(inputs)],
                    "output_dir": str(tmp_path / "out" / "01_registry"),
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
                    "input_roots": [str(inputs)],
                    "output_dir": str(tmp_path / "out" / "02_timeline"),
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
                    "input_roots": [str(inputs)],
                    "output_dir": str(tmp_path / "out" / "03_digest"),
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
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(
        voyage, config, run_id="g05_test_pos", base_dir=tmp_path / "out" / "dossier"
    )

    assert result.status == "executed"
    assert len(result.steps) == 3
    assert all(s.status == "executed" for s in result.steps)

    # Inspect Step 1 (document_registry)
    reg_step = result.steps[0]
    reg_report = RunLedger(Path(reg_step.ledger_path).parent).load(reg_step.run_id)
    assert reg_report.status is RunStatus.EXECUTED
    assert reg_report.metadata.get("rows") == 5

    # Inspect Step 2 (cost_timeline)
    timeline_step = result.steps[1]
    timeline_report = RunLedger(Path(timeline_step.ledger_path).parent).load(timeline_step.run_id)
    assert timeline_report.status is RunStatus.EXECUTED
    assert timeline_report.metadata.get("item_count") == 5
    assert timeline_report.metadata.get("undetermined_count") == 0
    assert timeline_report.metadata.get("projected_recurring_total") == 112.97
    assert timeline_report.metadata.get("projected_special_effects_total") == 148.0
    assert timeline_report.metadata.get("projected_total") == 260.97

    # Verify timeline.json payload structure
    timeline_json_path = (
        Path(timeline_step.output_dir) / f"{timeline_step.run_id}.timeline.json"
    )
    assert timeline_json_path.is_file()
    payload = json.loads(timeline_json_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "nemofold.cost-timeline.v1"
    assert payload["forecast_month"] == "2026-10"
    assert payload["projected_recurring_total"] == 112.97
    assert payload["projected_special_effects_total"] == 148.0
    assert payload["projected_total"] == 260.97
    assert len(payload["items"]) == 5

    # Verify timeline.svg exists
    svg_path = Path(timeline_step.output_dir) / f"{timeline_step.run_id}.timeline.svg"
    assert svg_path.is_file()
    svg_text = svg_path.read_text(encoding="utf-8")
    assert "<svg" in svg_text
    assert "Wiederkehrende Kosten" in svg_text

    # Inspect Step 3 (folder_digest)
    digest_step = result.steps[2]
    digest_report = RunLedger(Path(digest_step.ledger_path).parent).load(digest_step.run_id)
    assert digest_report.status is RunStatus.EXECUTED

    # Verify handoff in dossier
    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    handoff = dossier["steps"][2]["handoff"]
    assert handoff["format"] == "markdown"
    assert handoff["producer_workflow"] == "cost_timeline"
    assert handoff["status"] == "verified"


def test_g05_negative_unknown_due_dates_exact_forecast_blocked(tmp_path: Path) -> None:
    inputs = tmp_path / "contracts_undetermined"
    inputs.mkdir(parents=True)
    (inputs / "01_fitness.txt").write_text(CONTRACT_FITNESS, encoding="utf-8")
    (inputs / "02_undetermined.txt").write_text(
        "Vertrag: Nachzahlung Nebenkosten\n"
        "Betrag: 250,00 €\n"
        "Turnus: unregelmäßig\n"
        "Nächste Fälligkeit: unbestimmt\n",
        encoding="utf-8",
    )

    voyage = {
        "name": "test_g05_undetermined_blocked",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(inputs)],
                    "output_dir": str(tmp_path / "out" / "01_registry"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "recurring_costs",
                    },
                },
            },
            {
                "workflow": "cost_timeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "cost_timeline",
                    "input_roots": [str(inputs)],
                    "output_dir": str(tmp_path / "out" / "02_timeline"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "forecast_month": "2026-10",
                        "require_deterministic_due_dates": True,
                    },
                },
            },
        ],
    }
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(
        voyage, config, run_id="g05_test_undetermined", base_dir=tmp_path / "out" / "dossier"
    )

    assert result.status == "stopped"
    assert len(result.steps) == 2
    assert result.steps[0].status == "executed"
    step2 = result.steps[1]
    assert step2.status == "blocked"
    assert any("undetermined_cost_due_dates" in err for err in step2.errors)

    report = RunLedger(Path(step2.ledger_path).parent).load(step2.run_id)
    assert report.status is RunStatus.BLOCKED
    assert report.metadata.get("needs_user_input") is True
    assert report.metadata.get("undetermined_count") == 1

    needs_input_path = Path(step2.output_dir) / f"{step2.run_id}.needs-user-input.json"
    assert needs_input_path.is_file()
    needs_data = json.loads(needs_input_path.read_text(encoding="utf-8"))
    assert any(q["field"] == "cost_due_dates" for q in needs_data["questions"])


def test_g05_negative_missing_required_cost_column_blocked(tmp_path: Path) -> None:
    inputs = tmp_path / "contracts_missing_column"
    inputs.mkdir(parents=True)
    (inputs / "01_incomplete.txt").write_text(
        "Vertrag: Internet Glasfaser\n"
        "Turnus: monatlich\n"
        "Nächste Fälligkeit: 2026-10-01\n",
        encoding="utf-8",
    )

    voyage = {
        "name": "test_g05_missing_column_blocked",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(inputs)],
                    "output_dir": str(tmp_path / "out" / "01_registry"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "recurring_costs",
                        "required_columns": ["Betrag"],
                    },
                },
            },
        ],
    }
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(
        voyage, config, run_id="g05_test_missing_col", base_dir=tmp_path / "out" / "dossier"
    )

    assert result.status == "stopped"
    assert len(result.steps) == 1
    step1 = result.steps[0]
    assert step1.status == "blocked"
    assert any("needs_user_input:columns.Betrag" in err for err in step1.errors)

    report = RunLedger(Path(step1.ledger_path).parent).load(step1.run_id)
    assert report.status is RunStatus.BLOCKED
    assert report.metadata.get("needs_user_input") is True


def test_g05_negative_insufficient_cost_items_blocked(tmp_path: Path) -> None:
    inputs = tmp_path / "contracts_insufficient"
    inputs.mkdir(parents=True)
    (inputs / "01_single.txt").write_text(CONTRACT_FITNESS, encoding="utf-8")

    voyage = {
        "name": "test_g05_insufficient_items_blocked",
        "steps": [
            {
                "workflow": "cost_timeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "cost_timeline",
                    "input_roots": [str(inputs)],
                    "output_dir": str(tmp_path / "out" / "01_timeline"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "min_cost_items": 5,
                    },
                },
            },
        ],
    }
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(
        voyage, config, run_id="g05_test_sparse", base_dir=tmp_path / "out" / "dossier"
    )

    assert result.status == "stopped"
    assert len(result.steps) == 1
    step1 = result.steps[0]
    assert step1.status == "blocked"
    assert any("insufficient_cost_items:1<5" in err for err in step1.errors)
