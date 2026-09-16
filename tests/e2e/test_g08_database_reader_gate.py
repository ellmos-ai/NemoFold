"""End-to-end tests for Gate G08: Safe Specialist Database Access (Ellmos UC 42, 45)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, WorkflowBlocked
from nemofold.database_reader import (
    READ_ONLY_AUDIT_NOTICE,
    detect_database_profile,
    read_specialist_database,
    render_database_markdown,
    validate_sql_query,
)
from nemofold.voyage_runs import run_voyage


def _create_sample_hauslagerist(path: Path) -> Path:
    db_file = path / "hauslagerist.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE gegenstaende ("
            "id INTEGER PRIMARY KEY, "
            "gegenstand TEXT, "
            "lagerort TEXT, "
            "menge INTEGER, "
            "kategorie TEXT, "
            "zustand TEXT, "
            "notiz TEXT)"
        )
        conn.executemany(
            "INSERT INTO gegenstaende VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "Akkuschrauber", "Werkstatt", 1, "Werkzeug", "gut", "Im blauen Koffer"),
                (2, "Kaffeemaschine", "Küche", 1, "Haushaltsgerät", "neuwertig", "Entkalkt"),
            ],
        )
    return db_file


def _create_sample_mediplaner(path: Path) -> Path:
    db_file = path / "mediplaner.sqlite"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE rezepte ("
            "id INTEGER PRIMARY KEY, "
            "praeparat TEXT, "
            "wirkstoff TEXT, "
            "dosis TEXT, "
            "einnahmezeit TEXT, "
            "arzt TEXT, "
            "ausgestellt TEXT)"
        )
        conn.executemany(
            "INSERT INTO rezepte VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    1,
                    "Beispirol",
                    "Beispirolum",
                    "1-0-1",
                    "morgens/abends",
                    "Dr. Halvorsen",
                    "2026-02-03",
                ),
            ],
        )
    return db_file


# --------------------------------------------------------------------------- #
# Unit Tests
# --------------------------------------------------------------------------- #


def test_validate_sql_query_permits_safe_select() -> None:
    validate_sql_query(
        "SELECT * FROM gegenstaende WHERE lagerort = 'Küche'", ("gegenstaende",)
    )
    validate_sql_query(
        "WITH items AS (SELECT * FROM gegenstaende) SELECT * FROM items",
        ("gegenstaende",),
    )


def test_validate_sql_query_blocks_mutations() -> None:
    with pytest.raises(WorkflowBlocked) as exc_drop:
        validate_sql_query("DROP TABLE gegenstaende;", ("gegenstaende",))
    assert "database_modification_blocked" in exc_drop.value.errors[0]
    assert "DROP" in exc_drop.value.errors[0]

    with pytest.raises(WorkflowBlocked) as exc_insert:
        validate_sql_query(
            "INSERT INTO gegenstaende VALUES (1, 'X', 'Y')", ("gegenstaende",)
        )
    assert "database_modification_blocked" in exc_insert.value.errors[0]

    with pytest.raises(WorkflowBlocked) as exc_delete:
        validate_sql_query("DELETE FROM gegenstaende WHERE id = 1", ("gegenstaende",))
    assert "database_modification_blocked" in exc_delete.value.errors[0]


def test_validate_sql_query_blocks_multiple_statements() -> None:
    with pytest.raises(WorkflowBlocked) as exc_multi:
        validate_sql_query(
            "SELECT * FROM gegenstaende; DROP TABLE gegenstaende;", ("gegenstaende",)
        )
    assert "multiple_statements_forbidden" in exc_multi.value.errors[0]


def test_validate_sql_query_blocks_forbidden_tables() -> None:
    with pytest.raises(WorkflowBlocked) as exc_tbl:
        validate_sql_query("SELECT * FROM passwoerter", ("gegenstaende",))
    assert "table_not_allowed" in exc_tbl.value.errors[0]


def test_detect_database_profile() -> None:
    assert detect_database_profile("hauslagerist.db", ("gegenstaende",)) == "hauslagerist"
    assert detect_database_profile("inventory.db", ("gegenstaende", "lagerorte")) == "hauslagerist"
    assert detect_database_profile("mediplaner.sqlite", ("rezepte",)) == "mediplaner"
    assert detect_database_profile("custom.db", ("users",)) == "generic"


def test_read_specialist_database_hauslagerist(tmp_path: Path) -> None:
    db = _create_sample_hauslagerist(tmp_path)
    summary = read_specialist_database(db, source_id="src_haus", source_sha256="abc")
    assert summary.database_profile == "hauslagerist"
    assert summary.read_only_verified is True
    assert summary.total_records == 2
    assert len(summary.inventory_items) == 2
    assert summary.inventory_items[0].gegenstand == "Akkuschrauber"
    assert summary.inventory_items[0].lagerort == "Werkstatt"

    md = render_database_markdown(summary)
    assert "# HausLagerist Inventar-Register" in md
    assert READ_ONLY_AUDIT_NOTICE in md
    assert "Akkuschrauber" in md


def test_read_specialist_database_mediplaner(tmp_path: Path) -> None:
    db = _create_sample_mediplaner(tmp_path)
    summary = read_specialist_database(db, source_id="src_med", source_sha256="def")
    assert summary.database_profile == "mediplaner"
    assert summary.read_only_verified is True
    assert summary.total_records == 1
    assert len(summary.medication_items) == 1
    assert summary.medication_items[0].praeparat == "Beispirol"
    assert summary.medication_items[0].dosis == "1-0-1"

    md = render_database_markdown(summary)
    assert "# MediPlaner Medikations- und Einnahmeplan" in md
    assert READ_ONLY_AUDIT_NOTICE in md
    assert "Beispirol" in md


def test_read_specialist_database_missing_column_blocks(tmp_path: Path) -> None:
    db_bad = tmp_path / "bad.db"
    with sqlite3.connect(db_bad) as conn:
        conn.execute("CREATE TABLE gegenstaende (id INTEGER PRIMARY KEY, gegenstand TEXT)")
        conn.execute("INSERT INTO gegenstaende VALUES (1, 'Etwas')")

    with pytest.raises(WorkflowBlocked) as exc:
        read_specialist_database(
            db_bad,
            source_id="src_bad",
            source_sha256="123",
            requested_profile="hauslagerist",
        )
    assert "missing_schema_columns:gegenstaende:lagerort" in exc.value.errors[0]


# --------------------------------------------------------------------------- #
# E2E Voyage Tests
# --------------------------------------------------------------------------- #


def test_g08_positive_3step_voyage(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True)
    _create_sample_hauslagerist(input_dir)

    out_step1 = tmp_path / "out1"
    out_step2 = tmp_path / "out2"
    out_step3 = tmp_path / "out3"

    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g08_test",
        "title": "G08 Test Positive Voyage",
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
                    "parameters": {"formats": ["md"], "column_template": "inventory"},
                },
            },
            {
                "order": 2,
                "workflow": "database_reader",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "database_reader",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "formats": ["md"],
                        "database_profile": "hauslagerist",
                        "min_records": 1,
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
                    "output_dir": str(out_step3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"summary_length": 3},
                },
                "handoff": {"format": "markdown"},
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g08_test_pos")
    assert result.status == "executed"
    assert len(result.steps) == 3

    step2_json = out_step2 / "g08_test_pos_02.database-reader.json"
    step2_md = out_step2 / "g08_test_pos_02.database-reader.md"
    assert step2_json.is_file()
    assert step2_md.is_file()

    payload = json.loads(step2_json.read_text(encoding="utf-8"))
    assert payload["read_only_verified"] is True
    assert payload["total_records"] == 2
    assert payload["database_profile"] == "hauslagerist"


def test_g08_mutation_query_blocks_voyage(tmp_path: Path) -> None:
    input_dir = tmp_path / "input_mut"
    input_dir.mkdir(parents=True)
    _create_sample_hauslagerist(input_dir)

    out_step1 = tmp_path / "out_mut"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g08_mut_test",
        "title": "G08 Test Mutation Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "database_reader",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "database_reader",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "formats": ["md"],
                        "query": "DROP TABLE gegenstaende;",
                    },
                },
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g08_test_mut")
    assert result.status == "stopped"
    assert result.steps[-1].status == "blocked"
    assert result.steps[-1].ledger_path is not None
    report = json.loads(Path(result.steps[-1].ledger_path).read_text(encoding="utf-8"))
    assert any("database_modification_blocked" in f for f in report["errors"])


def test_g08_forbidden_table_blocks_voyage(tmp_path: Path) -> None:
    input_dir = tmp_path / "input_forbid"
    input_dir.mkdir(parents=True)
    _create_sample_hauslagerist(input_dir)

    out_step1 = tmp_path / "out_forbid"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g08_forbid_test",
        "title": "G08 Test Forbidden Table Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "database_reader",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "database_reader",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "formats": ["md"],
                        "target_tables": ["passwoerter"],
                    },
                },
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g08_test_forbid")
    assert result.status == "stopped"
    assert result.steps[-1].status == "blocked"
    assert result.steps[-1].ledger_path is not None
    report = json.loads(Path(result.steps[-1].ledger_path).read_text(encoding="utf-8"))
    assert any("table_not_allowed:passwoerter" in f for f in report["errors"])


def test_g08_insufficient_records_blocks_voyage(tmp_path: Path) -> None:
    input_dir = tmp_path / "input_empty"
    input_dir.mkdir(parents=True)
    db_empty = input_dir / "hauslagerist.db"
    with sqlite3.connect(db_empty) as conn:
        conn.execute(
            "CREATE TABLE gegenstaende (id INTEGER PRIMARY KEY, gegenstand TEXT, lagerort TEXT)"
        )

    out_step1 = tmp_path / "out_empty"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g08_empty_test",
        "title": "G08 Test Empty Database Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "database_reader",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "database_reader",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "formats": ["md"],
                        "min_records": 1,
                    },
                },
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g08_test_empty")
    assert result.status == "stopped"
    assert result.steps[-1].status == "blocked"
    needs_input = out_step1 / "g08_test_empty_01.needs-user-input.json"
    assert needs_input.is_file()
    payload = json.loads(needs_input.read_text(encoding="utf-8"))
    assert "Zu wenige Datensätze" in payload["questions"][0]["prompt"]
