"""End-to-end tests for Gate G06: Subscription Reconciliation (Ellmos UC 11)."""

from __future__ import annotations

import json
from pathlib import Path

from nemofold.application import ExecutionConfig
from nemofold.contracts import RunStatus
from nemofold.ledger import RunLedger
from nemofold.voyage_runs import run_voyage

SUB_STREAMING = (
    "Abo: Streaming Plus\nBetrag: 14,99 €\nTurnus: monatlich\nStatus: aktiv\nKonto: ACC-STREAM-01\n"
)

SUB_CLOUD = (
    "Abo: Cloud Speicher Pro\n"
    "Betrag: 9,99 €\n"
    "Turnus: monatlich\n"
    "Status: aktiv\n"
    "Konto: ACC-CLOUD-99\n"
)

SUB_GYM = (
    "Abo: Fitnessstudio StudioNord\n"
    "Betrag: 39,90 €\n"
    "Turnus: monatlich\n"
    "Status: aktiv\n"
    "Konto: ACC-GYM-12\n"
)

SUB_NEWSPAPER = (
    "Abo: Tageszeitung Digital\n"
    "Betrag: 19,90 €\n"
    "Turnus: monatlich\n"
    "Status: aktiv\n"
    "Konto: ACC-NEWS-05\n"
)

MSG_STREAMING = (
    "Absender: service@streaming-plus.de\n"
    "Betreff: Ihre Monatsrechnung Streaming Plus\n"
    "Datum: 2026-09-01\n"
    "Betrag: 14,99 €\n"
    "Konto: ACC-STREAM-01\n"
    "\n"
    "Vielen Dank für Ihre Zahlung. Ihr Streaming Plus Abonnement bleibt aktiv.\n"
)

MSG_CLOUD = (
    "Absender: billing@cloud-speicher.de\n"
    "Betreff: Tarifanpassung Cloud Speicher Pro\n"
    "Datum: 2026-09-05\n"
    "Betrag: 12,99 €\n"
    "Konto: ACC-CLOUD-99\n"
    "\n"
    "Wir passen unseren Monatspreis an. Neuer Betrag ab 01.10. beträgt 12,99 €.\n"
)

MSG_GYM = (
    "Absender: info@studionord.de\n"
    "Betreff: Kündigungsbestätigung StudioNord\n"
    "Datum: 2026-09-10\n"
    "Konto: ACC-GYM-12\n"
    "\n"
    "Wir bestätigen den Eingang Ihrer Kündigung. Vertragsende ist der 31.10.2026.\n"
)


def test_g06_positive_voyage_reconciles_subscriptions_and_messages(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "01_streaming.txt").write_text(SUB_STREAMING, encoding="utf-8")
    (inputs / "02_cloud.txt").write_text(SUB_CLOUD, encoding="utf-8")
    (inputs / "03_gym.txt").write_text(SUB_GYM, encoding="utf-8")
    (inputs / "04_newspaper.txt").write_text(SUB_NEWSPAPER, encoding="utf-8")
    (inputs / "msg_01.txt").write_text(MSG_STREAMING, encoding="utf-8")
    (inputs / "msg_02.txt").write_text(MSG_CLOUD, encoding="utf-8")
    (inputs / "msg_03.txt").write_text(MSG_GYM, encoding="utf-8")

    voyage = {
        "name": "test_g06_positive_voyage",
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
                        "title": "Abonnement-Inventar",
                    },
                },
            },
            {
                "workflow": "subscription_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "subscription_reconcile",
                    "input_roots": [str(inputs)],
                    "output_dir": str(tmp_path / "out" / "02_reconcile"),
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
        voyage, config, run_id="g06_test_pos", base_dir=tmp_path / "out" / "dossier"
    )

    assert result.status == "executed"
    assert len(result.steps) == 3
    assert all(s.status == "executed" for s in result.steps)

    # Inspect Step 1 (document_registry)
    reg_step = result.steps[0]
    reg_report = RunLedger(Path(reg_step.ledger_path).parent).load(reg_step.run_id)
    assert reg_report.status is RunStatus.EXECUTED
    assert reg_report.metadata.get("rows") == 7

    # Inspect Step 2 (subscription_reconcile)
    reconcile_step = result.steps[1]
    reconcile_report = RunLedger(Path(reconcile_step.ledger_path).parent).load(
        reconcile_step.run_id
    )
    assert reconcile_report.status is RunStatus.EXECUTED
    assert reconcile_report.metadata.get("total_declared") == 4
    assert reconcile_report.metadata.get("total_reconciled") == 1
    assert reconcile_report.metadata.get("total_discrepancies") == 2
    assert reconcile_report.metadata.get("total_unconfirmed") == 1
    assert reconcile_report.metadata.get("total_ambiguous") == 0

    reconcile_json_path = (
        Path(reconcile_step.output_dir) / f"{reconcile_step.run_id}.reconciliation.json"
    )
    assert reconcile_json_path.is_file()
    reconcile_data = json.loads(reconcile_json_path.read_text(encoding="utf-8"))
    assert reconcile_data["schema"] == "nemofold.subscription-reconciliation.v1"

    # Verify price discrepancy for Cloud
    cloud_match = next(
        m for m in reconcile_data["matches"] if "Cloud" in m["subscription"]["name"]
    )
    assert cloud_match["status"] == "discrepancy"
    assert any(d["kind"] == "price_change" for d in cloud_match["discrepancies"])

    # Verify cancellation discrepancy for Gym
    gym_match = next(
        m for m in reconcile_data["matches"] if "Fitness" in m["subscription"]["name"]
    )
    assert gym_match["status"] == "discrepancy"
    assert any(d["kind"] == "status_mismatch" for d in gym_match["discrepancies"])

    # Verify unconfirmed for Newspaper
    news_match = next(
        m for m in reconcile_data["matches"] if "zeitung" in m["subscription"]["name"].lower()
    )
    assert news_match["status"] == "unconfirmed"

    # Inspect Step 3 (folder_digest with handoff)
    digest_step = result.steps[2]
    digest_report = RunLedger(Path(digest_step.ledger_path).parent).load(digest_step.run_id)
    assert digest_report.status is RunStatus.EXECUTED
    assert digest_step.handoff is not None
    assert digest_step.handoff["status"] == "verified"
    assert digest_step.handoff["format"] == "markdown"


def test_g06_negative_ambiguous_matches_blocked(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs_ambiguous"
    inputs.mkdir(parents=True)
    (inputs / "01_music_personal.txt").write_text(
        "Abo: Musik Streaming\nBetrag: 9,99 €\nTurnus: monatlich\nStatus: aktiv\n",
        encoding="utf-8",
    )
    (inputs / "02_music_family.txt").write_text(
        "Abo: Musik Streaming\nBetrag: 14,99 €\nTurnus: monatlich\nStatus: aktiv\n",
        encoding="utf-8",
    )
    (inputs / "msg_ambiguous.txt").write_text(
        "Absender: billing@musik-streaming.de\n"
        "Betreff: Ihre Rechnung Musik Streaming\n"
        "Datum: 2026-09-12\n"
        "Betrag: 9,99 €\n"
        "\n"
        "Vielen Dank für Ihre Zahlung bei Musik Streaming.\n",
        encoding="utf-8",
    )

    voyage = {
        "name": "test_g06_ambiguous_blocked",
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
                "workflow": "subscription_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "subscription_reconcile",
                    "input_roots": [str(inputs)],
                    "output_dir": str(tmp_path / "out" / "02_reconcile"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "require_unambiguous_matches": True,
                    },
                },
            },
        ],
    }
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(
        voyage, config, run_id="g06_test_ambiguous", base_dir=tmp_path / "out" / "dossier"
    )

    assert result.status == "stopped"
    assert len(result.steps) == 2
    assert result.steps[0].status == "executed"
    step2 = result.steps[1]
    assert step2.status == "blocked"
    assert any("ambiguous_subscription_matches" in err for err in step2.errors)

    report = RunLedger(Path(step2.ledger_path).parent).load(step2.run_id)
    assert report.status is RunStatus.BLOCKED
    assert report.metadata.get("needs_user_input") is True

    needs_input_path = Path(step2.output_dir) / f"{step2.run_id}.needs-user-input.json"
    assert needs_input_path.is_file()
    needs_data = json.loads(needs_input_path.read_text(encoding="utf-8"))
    assert any("ambiguous_sub" in q["field"] for q in needs_data["questions"])


def test_g06_negative_missing_required_subscription_column_blocked(tmp_path: Path) -> None:
    inputs = tmp_path / "subs_missing_column"
    inputs.mkdir(parents=True)
    (inputs / "01_incomplete.txt").write_text(
        "Abo: Software Cloud\nTurnus: monatlich\nStatus: aktiv\n",
        encoding="utf-8",
    )

    voyage = {
        "name": "test_g06_missing_col_blocked",
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
        voyage, config, run_id="g06_test_missing_col", base_dir=tmp_path / "out" / "dossier"
    )

    assert result.status == "stopped"
    assert len(result.steps) == 1
    step1 = result.steps[0]
    assert step1.status == "blocked"
    assert any("needs_user_input:columns.Betrag" in err for err in step1.errors)

    report = RunLedger(Path(step1.ledger_path).parent).load(step1.run_id)
    assert report.status is RunStatus.BLOCKED
    assert report.metadata.get("needs_user_input") is True


def test_g06_negative_insufficient_subscriptions_blocked(tmp_path: Path) -> None:
    inputs = tmp_path / "subs_insufficient"
    inputs.mkdir(parents=True)
    (inputs / "01_single.txt").write_text(SUB_STREAMING, encoding="utf-8")

    voyage = {
        "name": "test_g06_insufficient_subs_blocked",
        "steps": [
            {
                "workflow": "subscription_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "subscription_reconcile",
                    "input_roots": [str(inputs)],
                    "output_dir": str(tmp_path / "out" / "01_reconcile"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "min_subscriptions": 5,
                    },
                },
            },
        ],
    }
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(
        voyage, config, run_id="g06_test_sparse", base_dir=tmp_path / "out" / "dossier"
    )

    assert result.status == "stopped"
    assert len(result.steps) == 1
    step1 = result.steps[0]
    assert step1.status == "blocked"
    assert any("insufficient_subscriptions:1<5" in err for err in step1.errors)
