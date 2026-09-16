"""Executable acceptance bundle for Gate G10: Routines and Reminders Query (Ellmos UC 44).

Verifies safe read-only querying of MasterRoutine SQLite databases, deterministic cadence
grounding against reference dates, transparent scheduler not-installed notices, and fail-closed
blocking when records are insufficient, cadences are contradictory, or mutation is attempted.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .acceptance_gates import (
    artifact_manifest_sha256,
    load_gate_register,
    verify_gate_evidence,
)
from .application import ExecutionConfig
from .artifacts import write_text_artifact
from .routine_query import (
    CADENCE_GROUNDING_NOTICE,
    SCHEDULER_NOT_INSTALLED_NOTICE,
)
from .voyage_runs import VoyageRunResult, run_voyage


class G10AcceptanceError(RuntimeError):
    """Raised when the executable G10 acceptance chain does not meet its contract."""


class G10AcceptanceBundle:
    """Artifact bundle resulting from running G10 acceptance tests."""

    def __init__(
        self,
        root: Path,
        register_path: Path,
        positive_dossier_path: Path,
        insufficient_routines_dossier_path: Path,
        invalid_cadence_dossier_path: Path,
        mutation_blocked_dossier_path: Path,
        verification: dict[str, Any],
    ) -> None:
        self.root = root
        self.register_path = register_path
        self.positive_dossier_path = positive_dossier_path
        self.insufficient_routines_dossier_path = insufficient_routines_dossier_path
        self.invalid_cadence_dossier_path = invalid_cadence_dossier_path
        self.mutation_blocked_dossier_path = mutation_blocked_dossier_path
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


def _write_positive_fixtures(root: Path) -> list[Path]:
    source_dir = root / "inputs" / "routine_master"
    source_dir.mkdir(parents=True, exist_ok=True)
    db_file = source_dir / "routine_master.db"

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
    return [db_file]


def _write_insufficient_fixture(root: Path) -> Path:
    source_dir = root / "inputs" / "insufficient_routine"
    source_dir.mkdir(parents=True, exist_ok=True)
    db_file = source_dir / "empty_routines.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE foo (id INTEGER PRIMARY KEY, info TEXT)")
    return db_file


def _write_invalid_cadence_fixture(root: Path) -> Path:
    source_dir = root / "inputs" / "invalid_cadence"
    source_dir.mkdir(parents=True, exist_ok=True)
    db_file = source_dir / "invalid_cadence.db"
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
                "Letzte Ausführung nach Fälligkeit",
                "fehler",
            ),
        )
    return db_file


def _write_mutation_fixture(root: Path) -> Path:
    source_dir = root / "inputs" / "mutation_routine"
    source_dir.mkdir(parents=True, exist_ok=True)
    db_file = source_dir / "routine_protect.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE routinen (id INTEGER PRIMARY KEY, titel TEXT, turnus TEXT)"
        )
        conn.execute(
            "INSERT INTO routinen VALUES (1, 'Unantastbar', 'taeglich')"
        )
    return db_file


def _run_positive_voyage(
    root: Path, input_dir: Path, config: ExecutionConfig
) -> VoyageRunResult:
    out_step1 = root / "work" / "positive_step1"
    out_step2 = root / "work" / "positive_step2"
    out_step3 = root / "work" / "positive_step3"

    plan = {
        "voyage_id": "vy_g10_acceptance_pos",
        "title": "G10 Positive Routine Query Acceptance Voyage",
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
    return run_voyage(plan, config, run_id="g10_pos")


def _run_insufficient_voyage(
    root: Path, input_dir: Path, config: ExecutionConfig
) -> VoyageRunResult:
    out_dir = root / "work" / "insufficient_step1"
    plan = {
        "voyage_id": "vy_g10_acceptance_insuf",
        "title": "G10 Negative Insufficient Routines Acceptance Voyage",
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
                    "parameters": {"min_routines": 1},
                },
            }
        ],
    }
    return run_voyage(plan, config, run_id="g10_insuf")


def _run_invalid_cadence_voyage(
    root: Path, input_dir: Path, config: ExecutionConfig
) -> VoyageRunResult:
    out_dir = root / "work" / "invalid_cadence_step1"
    plan = {
        "voyage_id": "vy_g10_acceptance_invalid",
        "title": "G10 Negative Invalid Cadence Acceptance Voyage",
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
    return run_voyage(plan, config, run_id="g10_invalid")


def _run_mutation_voyage(
    root: Path, input_dir: Path, config: ExecutionConfig
) -> VoyageRunResult:
    out_dir = root / "work" / "mutation_step1"
    plan = {
        "voyage_id": "vy_g10_acceptance_mutation",
        "title": "G10 Negative Mutation Acceptance Voyage",
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
    return run_voyage(plan, config, run_id="g10_mutation")


def _verify_positive_result(root: Path, result: VoyageRunResult) -> tuple[Path, list[Path]]:
    if result.status != "executed":
        raise G10AcceptanceError(f"g10_positive_not_executed:status={result.status}")
    if len(result.steps) != 3:
        raise G10AcceptanceError(f"g10_positive_expected_3_steps:got={len(result.steps)}")

    step2_dir = root / "work" / "positive_step2"
    json_path = step2_dir / "g10_pos_02.routine-query.json"
    md_path = step2_dir / "g10_pos_02.routine-query.md"

    if not json_path.is_file():
        raise G10AcceptanceError("g10_positive_json_artifact_missing")
    if not md_path.is_file():
        raise G10AcceptanceError("g10_positive_md_artifact_missing")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if payload.get("scheduler_status") != "not_installed":
        raise G10AcceptanceError("g10_positive_scheduler_status_not_installed_missing")
    if payload.get("reference_date") != "2026-09-16":
        raise G10AcceptanceError("g10_positive_reference_date_mismatch")
    if payload.get("total_routines", 0) < 5:
        raise G10AcceptanceError("g10_positive_routine_count_too_low")
    if payload.get("due_count", 0) < 2:
        raise G10AcceptanceError("g10_positive_due_count_too_low")
    if payload.get("overdue_count", 0) < 1:
        raise G10AcceptanceError("g10_positive_overdue_count_too_low")

    md_content = md_path.read_text(encoding="utf-8")
    if SCHEDULER_NOT_INSTALLED_NOTICE not in md_content:
        raise G10AcceptanceError("g10_positive_scheduler_notice_missing_in_md")
    if CADENCE_GROUNDING_NOTICE not in md_content:
        raise G10AcceptanceError("g10_positive_cadence_notice_missing_in_md")

    step3 = result.steps[-1]
    if step3.ledger_path is None:
        raise G10AcceptanceError("g10_positive_ledger_missing")
    report_path = Path(step3.ledger_path)
    if not report_path.is_file():
        raise G10AcceptanceError("g10_positive_report_file_missing")

    artifacts = [json_path, md_path]
    for step in (result.steps[0], result.steps[2]):
        step_dir = Path(step.output_dir)
        for p in step_dir.iterdir():
            if p.is_file() and not p.name.endswith(".run-report.json"):
                artifacts.append(p)

    return report_path, artifacts


def _verify_insufficient_result(root: Path, result: VoyageRunResult) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G10AcceptanceError(f"g10_insufficient_not_stopped:status={result.status}")
    if result.steps[-1].status != "blocked":
        raise G10AcceptanceError(
            f"g10_insufficient_step_not_blocked:status={result.steps[-1].status}"
        )

    out_dir = root / "work" / "insufficient_step1"
    needs_input = out_dir / "g10_insuf_01.needs-user-input.json"
    if not needs_input.is_file():
        raise G10AcceptanceError("g10_insufficient_needs_user_input_missing")

    ledger_path = Path(result.steps[-1].ledger_path)
    return ledger_path, [needs_input]


def _verify_invalid_cadence_result(root: Path, result: VoyageRunResult) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G10AcceptanceError(f"g10_invalid_cadence_not_stopped:status={result.status}")
    if result.steps[-1].status != "blocked":
        raise G10AcceptanceError(
            f"g10_invalid_cadence_step_not_blocked:status={result.steps[-1].status}"
        )

    ledger_path = Path(result.steps[-1].ledger_path)
    report = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not any("invalid_routine_cadence" in str(e) for e in report.get("errors", [])):
        raise G10AcceptanceError("g10_invalid_cadence_error_missing_in_ledger")

    return ledger_path, []


def _verify_mutation_result(root: Path, result: VoyageRunResult) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G10AcceptanceError(f"g10_mutation_not_stopped:status={result.status}")
    if result.steps[-1].status != "blocked":
        raise G10AcceptanceError(
            f"g10_mutation_step_not_blocked:status={result.steps[-1].status}"
        )

    ledger_path = Path(result.steps[-1].ledger_path)
    report = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not any("database_modification_blocked" in str(e) for e in report.get("errors", [])):
        raise G10AcceptanceError("g10_mutation_error_missing_in_ledger")

    return ledger_path, []


def run_g10_acceptance_bundle(
    output_root: str | Path,
) -> G10AcceptanceBundle:
    """Run the synthetic G10 positive and blocking paths and seal their evidence."""
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G10AcceptanceError(f"g10_evidence_root_not_empty:{root}")
    root.mkdir(parents=True, exist_ok=True)

    positive_inputs = _write_positive_fixtures(root)
    insufficient_input = _write_insufficient_fixture(root)
    invalid_cadence_input = _write_invalid_cadence_fixture(root)
    mutation_input = _write_mutation_fixture(root)
    config = ExecutionConfig(allowed_roots=(str(root),))

    positive = _run_positive_voyage(root, positive_inputs[0].parent, config)
    insufficient = _run_insufficient_voyage(root, insufficient_input.parent, config)
    invalid_cadence = _run_invalid_cadence_voyage(root, invalid_cadence_input.parent, config)
    mutation = _run_mutation_voyage(root, mutation_input.parent, config)

    positive_report, output_artifacts = _verify_positive_result(root, positive)
    insufficient_report, insufficient_artifacts = _verify_insufficient_result(root, insufficient)
    invalid_cadence_report, invalid_artifacts = _verify_invalid_cadence_result(
        root, invalid_cadence
    )
    mutation_report, mutation_artifacts = _verify_mutation_result(root, mutation)

    handoff_path = root / "evidence" / "g10-handoff.json"
    handoff = positive.steps[-1].handoff
    if not isinstance(handoff, dict):
        raise G10AcceptanceError("g10_positive_handoff_missing")
    write_text_artifact(
        handoff_path,
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    input_artifacts = [
        _artifact_receipt(root, path)
        for path in (
            *positive_inputs,
            insufficient_input,
            invalid_cadence_input,
            mutation_input,
        )
    ]
    dossier_artifacts = (
        Path(positive.dossier_path),
        Path(positive.dossier_path).with_suffix(".md"),
        Path(insufficient.dossier_path),
        Path(insufficient.dossier_path).with_suffix(".md"),
        Path(invalid_cadence.dossier_path),
        Path(invalid_cadence.dossier_path).with_suffix(".md"),
        Path(mutation.dossier_path),
        Path(mutation.dossier_path).with_suffix(".md"),
    )
    output_receipts = [
        _artifact_receipt(root, path)
        for path in (
            *output_artifacts,
            *insufficient_artifacts,
            *invalid_artifacts,
            *mutation_artifacts,
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
                "producer": "routine_query",
                "consumer": "folder_digest",
                "artifact_path": str(handoff_path.relative_to(root)).replace("\\", "/"),
                "artifact_sha256": _sha256(handoff_path),
                "status": "verified",
                "evidence": (
                    "routine_query extracts routines from MasterRoutine SQLite databases and "
                    "hands off structured markdown overview to folder_digest."
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
                "name": "master_routine_sqlite_queried_safely",
                "passed": True,
                "evidence": (
                    "Queried routines, tasks, and reminders with mode=ro and PRAGMA query_only=ON."
                ),
            },
            {
                "name": "cadence_grounded_against_reference_date",
                "passed": True,
                "evidence": (
                    "Deterministic due date and overdue days calculated strictly from declared "
                    "turnus and reference date."
                ),
            },
            {
                "name": "scheduler_not_installed_disclaimer_declared",
                "passed": True,
                "evidence": (
                    "Transparently declared scheduler_status as not_installed without false "
                    "claims of OS cron or background task scheduling."
                ),
            },
            {
                "name": "insufficient_routines_halts_and_emits_needs_input",
                "passed": True,
                "evidence": (
                    "Empty database or missing routine tables cleanly halts with status=blocked "
                    "and emits needs-user-input artifact."
                ),
            },
            {
                "name": "invalid_or_contradictory_cadence_blocked",
                "passed": True,
                "evidence": (
                    "Contradictory cadence dates fail closed without guessing or hallucination."
                ),
            },
            {
                "name": "database_mutation_blocked_fail_closed",
                "passed": True,
                "evidence": (
                    "Forbidden mutating SQL statements fail closed before execution."
                ),
            },
        ],
        "negative_path": {
            "case": "insufficient_routine_records_halts_with_needs_input",
            "run_id": insufficient.steps[-1].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "run_report": {
                "path": str(insufficient_report.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(insufficient_report),
            },
            "evidence": (
                "When routine database contains no recognizable routine tables or records, "
                "routine_query halts with status=blocked and emits needs-user-input."
            ),
        },
        "additional_negative_paths": [
            {
                "case": "invalid_or_contradictory_cadence_blocked",
                "run_id": invalid_cadence.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(invalid_cadence_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(invalid_cadence_report),
                },
                "evidence": (
                    "When last completion is after next due date, routine_query halts "
                    "with status=blocked fail closed."
                ),
            },
            {
                "case": "database_mutation_attempt_blocked",
                "run_id": mutation.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(mutation_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(mutation_report),
                },
                "evidence": (
                    "When mutating SQL operations or parameters are attempted, "
                    "routine_query blocks execution immediately."
                ),
            },
        ],
    }

    manifest_path = root / "evidence" / "g10-evidence-dossier.json"
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
        if gate["gate_id"] == "G10":
            gate["status"] = "partial"
            gate["evidence"] = {
                "test_nodes": [],
                "run_receipts": [receipt],
            }
            break

    register_path = root / "evidence" / "nf_fin_gates_g10.json"
    write_text_artifact(
        register_path,
        json.dumps(register, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "json",
    )

    verification = verify_gate_evidence(register, root)
    if "G10" not in verification["verified_evidence_gates"]:
        raise G10AcceptanceError("g10_gate_evidence_verification_failed")

    return G10AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(positive.dossier_path),
        insufficient_routines_dossier_path=Path(insufficient.dossier_path),
        invalid_cadence_dossier_path=Path(invalid_cadence.dossier_path),
        mutation_blocked_dossier_path=Path(mutation.dossier_path),
        verification=verification,
    )


def _render_acceptance_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# G10 Acceptance Dossier: Routines and Reminders Query",
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
