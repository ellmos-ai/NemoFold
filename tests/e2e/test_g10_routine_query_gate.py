"""End-to-end tests for Gate G10: Routines and Reminders Query (Ellmos UC 44)."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from nemofold.application import ExecutionConfig
from nemofold.routine_query import (
    CADENCE_GROUNDING_NOTICE,
    SCHEDULER_NOT_INSTALLED_NOTICE,
    calculate_cadence_due_date,
    read_routine_database,
    render_routine_markdown,
)
from nemofold.voyage_runs import run_voyage


def _create_sample_routine_db(path: Path) -> Path:
    db_file = path / "routine_master.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE routinen ("
            "id INTEGER PRIMARY KEY, "
            "titel TEXT, "
            "turnus TEXT, "
            "letzte_erledigung TEXT, "
            "naechste_faelligkeit TEXT, "
            "prioritaet TEXT, "
            "beschreibung TEXT, "
            "kategorie TEXT)"
        )
        conn.executemany(
            "INSERT INTO routinen VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    1,
                    "Wohnungsputz",
                    "woechentlich",
                    "2026-09-09",
                    "2026-09-16",
                    "hoch",
                    "Böden saugen und wischen",
                    "haushalt",
                ),
                (
                    2,
                    "Datensicherung",
                    "monatlich",
                    "2026-08-15",
                    "2026-09-15",
                    "mittel",
                    "Backup auf externe Festplatte",
                    "it",
                ),
                (
                    3,
                    "Blutdruck messen",
                    "täglich",
                    "2026-09-15",
                    "2026-09-16",
                    "hoch",
                    "Morgendliche Messung",
                    "gesundheit",
                ),
                (
                    4,
                    "Steuerunterlagen prüfen",
                    "quartalsweise",
                    "2026-07-01",
                    "2026-10-01",
                    "niedrig",
                    "Belege für Quartal sammeln",
                    "finanzen",
                ),
            ],
        )
        conn.execute(
            "CREATE TABLE aufgaben ("
            "id INTEGER PRIMARY KEY, "
            "aufgabe TEXT, "
            "turnus TEXT, "
            "faellig TEXT, "
            "prio TEXT, "
            "erledigt_am TEXT, "
            "status TEXT)"
        )
        conn.executemany(
            "INSERT INTO aufgaben VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    1,
                    "Pflanzen gießen",
                    "alle 3 tage",
                    "2026-09-17",
                    "normal",
                    "2026-09-14",
                    "offen",
                ),
            ],
        )
    return db_file


def _create_invalid_cadence_db(path: Path) -> Path:
    db_file = path / "routine_invalid.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE routinen ("
            "id INTEGER PRIMARY KEY, "
            "titel TEXT, "
            "turnus TEXT, "
            "letzte_erledigung TEXT, "
            "naechste_faelligkeit TEXT, "
            "prioritaet TEXT, "
            "beschreibung TEXT, "
            "kategorie TEXT)"
        )
        conn.execute(
            "INSERT INTO routinen VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                "Widersprüchliche Routine",
                "taeglich",
                "2026-09-20",
                "2026-09-10",
                "mittel",
                "Letzte Ausführung liegt nach Fälligkeit",
                "fehler",
            ),
        )
    return db_file


# --------------------------------------------------------------------------- #
# Unit Tests
# --------------------------------------------------------------------------- #


def test_calculate_cadence_due_date_valid() -> None:
    ref = date(2026, 9, 16)

    # Weekly from 2026-09-09 -> due 2026-09-16 (today, overdue 0)
    due, is_due, overdue_days, err = calculate_cadence_due_date(
        "woechentlich", "2026-09-09", None, ref
    )
    assert err is None
    assert due == "2026-09-16"
    assert is_due is True
    assert overdue_days == 0

    # Monthly from 2026-08-15 -> due 2026-09-14 (overdue by 2 days)
    due, is_due, overdue_days, err = calculate_cadence_due_date(
        "monatlich", "2026-08-15", None, ref
    )
    assert err is None
    assert due == "2026-09-14"
    assert is_due is True
    assert overdue_days == 2

    # Daily from 2026-09-15 -> due 2026-09-16
    due, is_due, overdue_days, err = calculate_cadence_due_date(
        "täglich", "2026-09-15", None, ref
    )
    assert err is None
    assert due == "2026-09-16"
    assert is_due is True
    assert overdue_days == 0

    # Custom "alle 5 tage" from 2026-09-10 -> due 2026-09-15 (overdue 1 day)
    due, is_due, overdue_days, err = calculate_cadence_due_date(
        "alle 5 tage", "2026-09-10", None, ref
    )
    assert err is None
    assert due == "2026-09-15"
    assert is_due is True
    assert overdue_days == 1

    # Future routine: daily from 2026-09-16 -> due 2026-09-17 (not due today)
    due, is_due, overdue_days, err = calculate_cadence_due_date(
        "täglich", "2026-09-16", None, ref
    )
    assert err is None
    assert due == "2026-09-17"
    assert is_due is False
    assert overdue_days == 0


def test_calculate_cadence_due_date_invalid() -> None:
    ref = date(2026, 9, 16)

    # Contradiction: last executed after next due
    due, is_due, overdue_days, err = calculate_cadence_due_date(
        "monatlich", "2026-09-20", "2026-09-10", ref
    )
    assert due is None
    assert err == "widerspruch_letzte_ausfuehrung_nach_faelligkeit"

    # Unknown cadence format without dates
    due, is_due, overdue_days, err = calculate_cadence_due_date(
        "irgendwann_spaeter", None, None, ref
    )
    assert due is None
    assert err is not None and "unbekannter_turnus" in err


def test_read_routine_database(tmp_path: Path) -> None:
    db_file = _create_sample_routine_db(tmp_path)
    ref = date(2026, 9, 16)
    items = read_routine_database(db_file, source_id="test_db", ref_date=ref)

    assert len(items) == 5
    titles = {item.title for item in items}
    assert "Wohnungsputz" in titles
    assert "Datensicherung" in titles
    assert "Blutdruck messen" in titles
    assert "Steuerunterlagen prüfen" in titles
    assert "Pflanzen gießen" in titles

    md = render_routine_markdown(items, ref)
    assert SCHEDULER_NOT_INSTALLED_NOTICE in md
    assert CADENCE_GROUNDING_NOTICE in md
    assert "Wohnungsputz" in md
    assert "Datensicherung" in md


# --------------------------------------------------------------------------- #
# Voyage E2E Tests
# --------------------------------------------------------------------------- #


def test_g10_positive_routine_voyage(tmp_path: Path) -> None:
    input_dir = tmp_path / "routine_sources"
    input_dir.mkdir(parents=True)
    _create_sample_routine_db(input_dir)

    out_step1 = tmp_path / "out_step1"
    out_step2 = tmp_path / "out_step2"
    out_step3 = tmp_path / "out_step3"

    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g10_positive_routines",
        "title": "G10 Positive Routine Query Voyage",
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
                "workflow": "routine_query",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "routine_query",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "reference_date": "2026-09-16",
                        "min_routines": 2,
                        "require_valid_cadence": True,
                        "require_read_only": True,
                        "formats": ["md", "json"],
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

    result = run_voyage(plan, config, run_id="g10_pos_routine")
    assert result.status == "executed"
    assert len(result.steps) == 3

    step2_json = out_step2 / "g10_pos_routine_02.routine-query.json"
    step2_md = out_step2 / "g10_pos_routine_02.routine-query.md"

    assert step2_json.is_file()
    assert step2_md.is_file()

    payload = json.loads(step2_json.read_text(encoding="utf-8"))
    assert payload["scheduler_status"] == "not_installed"
    assert payload["reference_date"] == "2026-09-16"
    assert payload["total_routines"] == 5
    assert payload["due_count"] >= 2
    assert payload["overdue_count"] >= 1
    assert payload["invalid_count"] == 0

    md_content = step2_md.read_text(encoding="utf-8")
    assert SCHEDULER_NOT_INSTALLED_NOTICE in md_content
    assert CADENCE_GROUNDING_NOTICE in md_content
    assert "Wohnungsputz" in md_content
    assert "Datensicherung" in md_content


def test_g10_negative_insufficient_routines_blocked(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty_sources"
    empty_dir.mkdir(parents=True)
    empty_db = empty_dir / "empty.db"
    with sqlite3.connect(empty_db) as conn:
        conn.execute("CREATE TABLE foo (id INT, bar TEXT)")

    out_dir = tmp_path / "out_insufficient"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g10_neg_insufficient",
        "title": "G10 Negative Insufficient Routines",
        "steps": [
            {
                "order": 1,
                "workflow": "routine_query",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "routine_query",
                    "input_roots": [str(empty_dir)],
                    "output_dir": str(out_dir),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"min_routines": 1},
                },
            }
        ],
    }

    result = run_voyage(plan, config, run_id="g10_neg_insufficient")
    assert result.status == "stopped"
    assert result.steps[-1].status == "blocked"
    ask_file = out_dir / "g10_neg_insufficient_01.needs-user-input.json"
    assert ask_file.is_file()
    ask_data = json.loads(ask_file.read_text(encoding="utf-8"))
    assert ask_data["workflow"] == "routine_query"


def test_g10_negative_invalid_cadence_blocked(tmp_path: Path) -> None:
    input_dir = tmp_path / "invalid_sources"
    input_dir.mkdir(parents=True)
    _create_invalid_cadence_db(input_dir)

    out_dir = tmp_path / "out_invalid"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g10_neg_invalid",
        "title": "G10 Negative Invalid Cadence",
        "steps": [
            {
                "order": 1,
                "workflow": "routine_query",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "routine_query",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_dir),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "reference_date": "2026-09-16",
                        "min_routines": 1,
                        "require_valid_cadence": True,
                    },
                },
            }
        ],
    }

    result = run_voyage(plan, config, run_id="g10_neg_invalid")
    assert result.status == "stopped"
    assert result.steps[-1].status == "blocked"
    assert result.steps[-1].ledger_path is not None
    report = json.loads(Path(result.steps[-1].ledger_path).read_text(encoding="utf-8"))
    assert any("invalid_routine_cadence" in str(e) for e in report.get("errors", []))


def test_g10_negative_database_mutation_blocked(tmp_path: Path) -> None:
    input_dir = tmp_path / "mutation_sources"
    input_dir.mkdir(parents=True)
    _create_sample_routine_db(input_dir)

    out_dir = tmp_path / "out_mutation"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g10_neg_mutation",
        "title": "G10 Negative Mutation Blocked",
        "steps": [
            {
                "order": 1,
                "workflow": "routine_query",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "routine_query",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_dir),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "query": "DELETE FROM routinen WHERE id = 1;",
                        "require_read_only": True,
                    },
                },
            }
        ],
    }

    result = run_voyage(plan, config, run_id="g10_neg_mutation")
    assert result.status == "stopped"
    assert result.steps[-1].status == "blocked"
    assert result.steps[-1].ledger_path is not None
    report = json.loads(Path(result.steps[-1].ledger_path).read_text(encoding="utf-8"))
    assert any(
        "database_modification_blocked" in str(e) or "mutation" in str(e)
        for e in report.get("errors", [])
    )
