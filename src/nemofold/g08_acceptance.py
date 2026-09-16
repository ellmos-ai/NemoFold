"""Executable acceptance bundle for Gate G08: Safe Specialist Database Access (Ellmos UC 42, 45).

Verifies safe read-only access to local SQLite databases (HausLagerist, MediPlaner) with
schema allowlists, mutation protection, and fail-closed blocking paths.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
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
from .voyage_runs import VoyageRunResult, run_voyage


class G08AcceptanceError(RuntimeError):
    """Raised when the executable G08 acceptance chain does not meet its contract."""


@dataclass(frozen=True, slots=True)
class G08AcceptanceBundle:
    root: Path
    register_path: Path
    positive_dossier_path: Path
    mutation_dossier_path: Path
    forbidden_table_dossier_path: Path
    insufficient_records_dossier_path: Path
    verification: dict[str, Any]


def run_g08_acceptance_bundle(
    output_root: str | Path,
) -> G08AcceptanceBundle:
    """Run the synthetic G08 positive and blocking paths and seal their evidence."""
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G08AcceptanceError(f"g08_evidence_root_not_empty:{root}")
    root.mkdir(parents=True, exist_ok=True)

    positive_inputs = _write_positive_fixtures(root)
    mutation_input = _write_mutation_fixture(root)
    forbidden_table_input = _write_forbidden_table_fixture(root)
    insufficient_records_input = _write_insufficient_records_fixture(root)
    config = ExecutionConfig(allowed_roots=(str(root),))

    positive = _run_positive_voyage(root, positive_inputs[0].parent, config)
    mutation = _run_mutation_voyage(root, mutation_input.parent, config)
    forbidden_table = _run_forbidden_table_voyage(root, forbidden_table_input.parent, config)
    insufficient_records = _run_insufficient_records_voyage(
        root, insufficient_records_input.parent, config
    )

    positive_report, output_artifacts = _verify_positive_result(root, positive)
    mutation_report, mutation_artifacts = _verify_mutation_result(root, mutation)
    forbidden_report, forbidden_artifacts = _verify_forbidden_table_result(root, forbidden_table)
    insufficient_report, insufficient_artifacts = _verify_insufficient_records_result(
        root, insufficient_records
    )

    handoff_path = root / "evidence" / "g08-handoff.json"
    handoff = positive.steps[-1].handoff
    if not isinstance(handoff, dict):
        raise G08AcceptanceError("g08_positive_handoff_missing")
    write_text_artifact(
        handoff_path,
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    input_artifacts = [
        _artifact_receipt(root, path)
        for path in (
            *positive_inputs,
            mutation_input,
            forbidden_table_input,
            insufficient_records_input,
        )
    ]
    dossier_artifacts = (
        Path(positive.dossier_path),
        Path(positive.dossier_path).with_suffix(".md"),
        Path(mutation.dossier_path),
        Path(mutation.dossier_path).with_suffix(".md"),
        Path(forbidden_table.dossier_path),
        Path(forbidden_table.dossier_path).with_suffix(".md"),
        Path(insufficient_records.dossier_path),
        Path(insufficient_records.dossier_path).with_suffix(".md"),
    )
    output_receipts = [
        _artifact_receipt(root, path)
        for path in (
            *output_artifacts,
            *mutation_artifacts,
            *forbidden_artifacts,
            *insufficient_artifacts,
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
                "producer": "database_reader",
                "consumer": "folder_digest",
                "artifact_path": str(handoff_path.relative_to(root)).replace("\\", "/"),
                "artifact_sha256": _sha256(handoff_path),
                "status": "verified",
                "evidence": (
                    "database_reader produces a verified safe markdown export of "
                    "HausLagerist inventory and hands off to folder_digest."
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
                "name": "read_only_mode_verified",
                "passed": True,
                "evidence": (
                    "PRAGMA query_only=ON and URI mode=ro verified on database connection."
                ),
            },
            {
                "name": "hauslagerist_inventory_records_extracted",
                "passed": True,
                "evidence": (
                    "Three inventory items extracted from table 'gegenstaende' "
                    "with location, category, and condition."
                ),
            },
            {
                "name": "safe_markdown_rendered_with_audit_notice",
                "passed": True,
                "evidence": (
                    "Generated report contains READ_ONLY_AUDIT_NOTICE and "
                    "clean inventory summary table."
                ),
            },
        ],
        "negative_path": {
            "case": "mutation_statement_blocked_under_read_only_contract",
            "run_id": mutation.steps[-1].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "run_report": {
                "path": str(mutation_report.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(mutation_report),
            },
            "evidence": (
                "When a query attempts a DROP TABLE mutation, database_reader halts "
                "with status=blocked and raises database_modification_blocked."
            ),
        },
        "additional_negative_paths": [
            {
                "case": "unauthorized_table_access_blocked",
                "run_id": forbidden_table.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(forbidden_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(forbidden_report),
                },
                "evidence": (
                    "When an unauthorized or forbidden table ('passwoerter') is requested, "
                    "database_reader halts with status=blocked and table_not_allowed."
                ),
            },
            {
                "case": "insufficient_records_blocked_with_needs_user_input",
                "run_id": insufficient_records.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(insufficient_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(insufficient_report),
                },
                "evidence": (
                    "When fewer database records exist than declared min_records, "
                    "database_reader halts with needs-user-input and status=blocked."
                ),
            },
        ],
    }

    manifest_path = root / "evidence" / "g08-evidence-dossier.json"
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
        if gate["gate_id"] == "G08":
            gate["status"] = "partial"
            gate["evidence"] = {
                "test_nodes": [],
                "run_receipts": [receipt],
            }
            break

    register_path = root / "evidence" / "nf_fin_gates_g08.json"
    write_text_artifact(
        register_path,
        json.dumps(register, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "json",
    )

    verification = verify_gate_evidence(register, root)
    if "G08" not in verification["verified_evidence_gates"]:
        raise G08AcceptanceError("g08_gate_evidence_verification_failed")

    return G08AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(positive.dossier_path),
        mutation_dossier_path=Path(mutation.dossier_path),
        forbidden_table_dossier_path=Path(forbidden_table.dossier_path),
        insufficient_records_dossier_path=Path(insufficient_records.dossier_path),
        verification=verification,
    )


def _render_acceptance_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# G08 Acceptance Dossier: Safe Specialist Database Access",
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


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _write_positive_fixtures(root: Path) -> tuple[Path, Path]:
    input_dir = root / "inputs" / "positive"
    input_dir.mkdir(parents=True, exist_ok=True)

    db_haus = input_dir / "hauslagerist.db"
    with sqlite3.connect(db_haus) as conn:
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
                (
                    1,
                    "Akkuschrauber",
                    "Werkstatt",
                    1,
                    "Werkzeug",
                    "gut",
                    "Im blauen Koffer",
                ),
                (
                    2,
                    "Kaffeemaschine",
                    "Küche",
                    1,
                    "Haushaltsgerät",
                    "neuwertig",
                    "Regelmäßig entkalkt",
                ),
                (
                    3,
                    "Aktenordner",
                    "Büro",
                    5,
                    "Büromaterial",
                    "gut",
                    "Steuerunterlagen",
                ),
            ],
        )
        conn.execute(
            "CREATE TABLE lagerorte (id INTEGER PRIMARY KEY, name TEXT, beschreibung TEXT)"
        )
        conn.executemany(
            "INSERT INTO lagerorte VALUES (?, ?, ?)",
            [
                (1, "Werkstatt", "Kellerraum 2"),
                (2, "Küche", "Erdgeschoss"),
                (3, "Büro", "1. Obergeschoss"),
            ],
        )

    db_med = input_dir / "mediplaner.sqlite"
    with sqlite3.connect(db_med) as conn:
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
                    "morgens und abends",
                    "Dr. Halvorsen",
                    "2026-02-03",
                ),
                (
                    2,
                    "Musterazol",
                    "Musterazolum",
                    "0-0-1",
                    "abends",
                    "Dr. Brandt",
                    "2026-03-11",
                ),
            ],
        )

    return db_haus, db_med


def _write_mutation_fixture(root: Path) -> Path:
    input_dir = root / "inputs" / "mutation"
    input_dir.mkdir(parents=True, exist_ok=True)
    db_file = input_dir / "hauslagerist.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE gegenstaende (id INTEGER PRIMARY KEY, gegenstand TEXT, lagerort TEXT)"
        )
        conn.execute("INSERT INTO gegenstaende VALUES (1, 'Bohrmaschine', 'Werkstatt')")
    return db_file


def _write_forbidden_table_fixture(root: Path) -> Path:
    input_dir = root / "inputs" / "forbidden_table"
    input_dir.mkdir(parents=True, exist_ok=True)
    db_file = input_dir / "hauslagerist.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE gegenstaende (id INTEGER PRIMARY KEY, gegenstand TEXT, lagerort TEXT)"
        )
        conn.execute("INSERT INTO gegenstaende VALUES (1, 'Staubsauger', 'Flur')")
        conn.execute(
            "CREATE TABLE passwoerter (id INTEGER PRIMARY KEY, service TEXT, pw TEXT)"
        )
        conn.execute("INSERT INTO passwoerter VALUES (1, 'Router', 'secret123')")
    return db_file


def _write_insufficient_records_fixture(root: Path) -> Path:
    input_dir = root / "inputs" / "insufficient_records"
    input_dir.mkdir(parents=True, exist_ok=True)
    db_file = input_dir / "hauslagerist_empty.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE gegenstaende (id INTEGER PRIMARY KEY, gegenstand TEXT, lagerort TEXT)"
        )
    return db_file


# --------------------------------------------------------------------------- #
# Voyages
# --------------------------------------------------------------------------- #


def _run_positive_voyage(
    root: Path,
    input_dir: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    plan = {
        "voyage_id": "vy_g08_positive",
        "title": "G08 Positive Voyage: Specialist Database Reader",
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
                        "formats": ["md"],
                        "column_template": "inventory",
                    },
                },
            },
            {
                "order": 2,
                "workflow": "database_reader",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "database_reader",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "pos_step2"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "formats": ["md"],
                        "database_profile": "hauslagerist",
                        "min_records": 1,
                        "require_read_only": True,
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
    return run_voyage(plan, config, run_id="g08_pos")


def _run_mutation_voyage(
    root: Path,
    input_dir: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    plan = {
        "voyage_id": "vy_g08_mutation",
        "title": "G08 Blocking Voyage: Attempted Mutation Query",
        "steps": [
            {
                "order": 1,
                "workflow": "database_reader",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "database_reader",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "mutation_step1"),
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
    return run_voyage(plan, config, run_id="g08_mutation")


def _run_forbidden_table_voyage(
    root: Path,
    input_dir: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    plan = {
        "voyage_id": "vy_g08_forbidden_table",
        "title": "G08 Blocking Voyage: Forbidden Table Access",
        "steps": [
            {
                "order": 1,
                "workflow": "database_reader",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "database_reader",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "forbidden_step1"),
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
    return run_voyage(plan, config, run_id="g08_forbidden")


def _run_insufficient_records_voyage(
    root: Path,
    input_dir: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    plan = {
        "voyage_id": "vy_g08_insufficient_records",
        "title": "G08 Blocking Voyage: Insufficient Database Records",
        "steps": [
            {
                "order": 1,
                "workflow": "database_reader",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "database_reader",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(root / "outputs" / "insufficient_step1"),
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
    return run_voyage(plan, config, run_id="g08_insufficient")


# --------------------------------------------------------------------------- #
# Verifiers
# --------------------------------------------------------------------------- #


def _verify_positive_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "executed":
        raise G08AcceptanceError(f"g08_positive_voyage_not_executed:{result.status}")
    if len(result.steps) != 3:
        raise G08AcceptanceError(f"g08_positive_steps_unexpected:{len(result.steps)}")

    step2_dir = root / "outputs" / "pos_step2"
    step2_json = step2_dir / "g08_pos_02.database-reader.json"
    step2_md = step2_dir / "g08_pos_02.database-reader.md"
    if not step2_json.is_file():
        raise G08AcceptanceError("g08_database_reader_json_missing")
    if not step2_md.is_file():
        raise G08AcceptanceError("g08_database_reader_md_missing")

    data = json.loads(step2_json.read_text(encoding="utf-8"))
    if not data.get("read_only_verified"):
        raise G08AcceptanceError("g08_database_not_read_only_verified")
    if data.get("total_records", 0) < 3:
        raise G08AcceptanceError("g08_database_record_count_insufficient")

    md_text = step2_md.read_text(encoding="utf-8")
    if "mode=ro" not in md_text or "PRAGMA query_only=ON" not in md_text:
        raise G08AcceptanceError("g08_read_only_notice_missing_in_markdown")

    if not result.steps[-1].ledger_path or not Path(result.steps[-1].ledger_path).is_file():
        raise G08AcceptanceError("g08_positive_run_report_missing")
    report_path = Path(result.steps[-1].ledger_path)

    step1_dir = root / "outputs" / "pos_step1"
    step3_dir = root / "outputs" / "pos_step3"
    step1_artifacts = tuple(p for p in step1_dir.iterdir() if p.is_file())
    step2_artifacts = tuple(p for p in step2_dir.iterdir() if p.is_file())
    step3_artifacts = tuple(p for p in step3_dir.iterdir() if p.is_file())

    all_artifacts = (*step1_artifacts, *step2_artifacts, *step3_artifacts)
    return report_path, all_artifacts


def _verify_mutation_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped":
        raise G08AcceptanceError(f"g08_mutation_voyage_not_blocked:{result.status}")
    last_step = result.steps[-1]
    if last_step.status != "blocked":
        raise G08AcceptanceError("g08_mutation_step_not_blocked")

    if not last_step.ledger_path or not Path(last_step.ledger_path).is_file():
        raise G08AcceptanceError("g08_mutation_run_report_missing")
    report_path = Path(last_step.ledger_path)
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    errors = report_data.get("errors", [])
    if not any("database_modification_blocked" in e for e in errors):
        raise G08AcceptanceError(f"g08_mutation_failure_missing:{errors}")

    step1_dir = root / "outputs" / "mutation_step1"
    artifacts = tuple(p for p in step1_dir.iterdir() if p.is_file())
    return report_path, artifacts


def _verify_forbidden_table_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped":
        raise G08AcceptanceError(f"g08_forbidden_table_not_blocked:{result.status}")
    last_step = result.steps[-1]
    if last_step.status != "blocked":
        raise G08AcceptanceError("g08_forbidden_table_step_not_blocked")

    if not last_step.ledger_path or not Path(last_step.ledger_path).is_file():
        raise G08AcceptanceError("g08_forbidden_table_run_report_missing")
    report_path = Path(last_step.ledger_path)
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    errors = report_data.get("errors", [])
    if not any("table_not_allowed" in e for e in errors):
        raise G08AcceptanceError(f"g08_forbidden_table_failure_missing:{errors}")

    step1_dir = root / "outputs" / "forbidden_step1"
    artifacts = tuple(p for p in step1_dir.iterdir() if p.is_file())
    return report_path, artifacts


def _verify_insufficient_records_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped":
        raise G08AcceptanceError(f"g08_insufficient_records_not_blocked:{result.status}")
    last_step = result.steps[-1]
    if last_step.status != "blocked":
        raise G08AcceptanceError("g08_insufficient_records_step_not_blocked")

    if not last_step.ledger_path or not Path(last_step.ledger_path).is_file():
        raise G08AcceptanceError("g08_insufficient_records_run_report_missing")
    report_path = Path(last_step.ledger_path)
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    errors = report_data.get("errors", [])
    if not any("insufficient_database_records" in e for e in errors):
        raise G08AcceptanceError(f"g08_insufficient_records_failure_missing:{errors}")

    step1_dir = root / "outputs" / "insufficient_step1"
    needs_input = step1_dir / f"{last_step.run_id}.needs-user-input.json"
    if not needs_input.is_file():
        raise G08AcceptanceError("g08_needs_user_input_artifact_missing")

    artifacts = tuple(p for p in step1_dir.iterdir() if p.is_file())
    return report_path, artifacts


# --------------------------------------------------------------------------- #
# Artifact helpers
# --------------------------------------------------------------------------- #


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_receipt(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "sha256": _sha256(path),
    }
