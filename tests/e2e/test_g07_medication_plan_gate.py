"""End-to-end tests for Gate G07: Medication Plan Consolidation (Ellmos UC 23, 37)."""

from __future__ import annotations

import json
from pathlib import Path

from nemofold.application import ExecutionConfig
from nemofold.contracts import RunStatus
from nemofold.ledger import RunLedger
from nemofold.medication_reconcile import (
    extract_medications_from_texts,
    reconcile_medications,
)
from nemofold.voyage_runs import run_voyage

DOC_HAUSARZT = (
    "Arzt: Dr. med. Weber (Hausarzt)\n"
    "Datum: 2026-08-15\n"
    "\n"
    "Medikament: L-Thyroxin Henning\n"
    "Wirkstoff: Levothyroxin-Natrium\n"
    "Dosierung: 75 µg\n"
    "Einnahme: 1-0-0-0 morgens nüchtern\n"
    "Indikation: Hypothyreose\n"
    "Status: laufend\n"
    "\n"
    "Medikament: Ramipril-ratiopharm\n"
    "Wirkstoff: Ramipril\n"
    "Dosierung: 5 mg\n"
    "Einnahme: 1-0-0-0 morgens\n"
    "Indikation: Hypertonie\n"
    "Status: laufend\n"
    "\n"
    "Medikament: Pantoprazol TAD\n"
    "Wirkstoff: Pantoprazol\n"
    "Dosierung: 20 mg\n"
    "Einnahme: 0-0-1-0 abends\n"
    "Indikation: Magenschutz\n"
    "Status: laufend\n"
)

DOC_KLINIK = (
    "Arzt: Klinikum Mitte, Abt. Endokrinologie\n"
    "Datum: 2026-09-02\n"
    "\n"
    "Medikament: L-Thyroxin Henning\n"
    "Wirkstoff: Levothyroxin-Natrium\n"
    "Dosierung: 100 µg\n"
    "Einnahme: 1-0-0-0 morgens nüchtern\n"
    "Indikation: Hypothyreose\n"
    "Status: laufend\n"
    "\n"
    "Medikament: Ramipril-ratiopharm\n"
    "Wirkstoff: Ramipril\n"
    "Dosierung: 5 mg\n"
    "Einnahme: 1-0-0-0 morgens\n"
    "Indikation: Hypertonie\n"
    "Status: laufend\n"
    "\n"
    "Medikament: Metformin HEXAL\n"
    "Wirkstoff: Metforminhydrochlorid\n"
    "Dosierung: 1000 mg\n"
    "Einnahme: 1-0-1-0 zu den Mahlzeiten\n"
    "Indikation: Diabetes mellitus Typ 2\n"
    "Status: laufend\n"
)


def test_medication_extraction_and_reconciliation_unit() -> None:
    texts = {
        "doc1.txt": DOC_HAUSARZT,
        "doc2.txt": DOC_KLINIK,
    }
    records = extract_medications_from_texts(["doc1.txt", "doc2.txt"], texts)
    assert len(records) == 6

    # 1. Unresolved: conflicting dosages for L-Thyroxin (75 vs 100)
    summary_unresolved = reconcile_medications(records)
    assert summary_unresolved.has_blocking_conflicts
    assert summary_unresolved.unresolved_conflict_count == 1
    assert summary_unresolved.unresolved_conflicts[0].medication_name == "L-Thyroxin Henning"
    assert summary_unresolved.unresolved_conflicts[0].kind == "conflicting_dosages"

    # 2. Resolved with user correction
    corrections = {
        "L-Thyroxin Henning": {
            "dosage": "100 µg",
            "schedule": "1-0-0-0 morgens nüchtern",
            "confirmed_by": "Dr. Weber am 05.09. bestätigt",
        }
    }
    summary_resolved = reconcile_medications(records, user_corrections=corrections)
    assert not summary_resolved.has_blocking_conflicts
    assert summary_resolved.unresolved_conflict_count == 0
    assert summary_resolved.resolved_conflict_count == 1
    assert summary_resolved.total_medications == 4

    l_thyroxin = next(m for m in summary_resolved.consolidated if "L-Thyroxin" in m.name)
    assert l_thyroxin.dosage == "100 µg"
    assert l_thyroxin.resolution_note == "Dr. Weber am 05.09. bestätigt"


def test_duplicate_active_ingredient_detection() -> None:
    doc = (
        "Medikament: Pantozol\n"
        "Wirkstoff: Pantoprazol\n"
        "Dosierung: 40 mg\n"
        "Einnahme: morgens\n"
        "\n"
        "Medikament: Pantoprazol TAD\n"
        "Wirkstoff: Pantoprazol\n"
        "Dosierung: 20 mg\n"
        "Einnahme: abends\n"
    )
    records = extract_medications_from_texts(["test.txt"], {"test.txt": doc})
    assert len(records) == 2
    summary = reconcile_medications(records)
    assert summary.duplicate_ingredient_count == 1
    dup_conf = next(c for c in summary.conflicts if c.kind == "duplicate_active_ingredient")
    assert "Pantoprazol" in dup_conf.description


def test_g07_positive_3_step_voyage(tmp_path: Path) -> None:
    in_dir = tmp_path / "inputs"
    in_dir.mkdir(parents=True)
    (in_dir / "01_hausarzt.txt").write_text(DOC_HAUSARZT, encoding="utf-8")
    (in_dir / "02_klinik.txt").write_text(DOC_KLINIK, encoding="utf-8")

    out_root = tmp_path / "outputs"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))

    plan = {
        "voyage_id": "vy_g07_positive_test",
        "title": "G07 Positive Test Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(in_dir)],
                    "output_dir": str(out_root / "step1"),
                    "parameters": {
                        "column_template": "medication_plan",
                        "formats": ["md"],
                    },
                },
            },
            {
                "order": 2,
                "workflow": "medication_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "medication_reconcile",
                    "input_roots": [str(in_dir)],
                    "output_dir": str(out_root / "step2"),
                    "parameters": {
                        "formats": ["md", "json"],
                        "min_medications": 2,
                        "require_unambiguous_dosages": True,
                        "application_domain": "medical_reports",
                        "user_corrections": {
                            "L-Thyroxin Henning": {
                                "dosage": "100 µg",
                                "schedule": "1-0-0-0 morgens nüchtern",
                                "confirmed_by": "Dr. Weber telefonisch am 05.09.2026 bestätigt",
                            }
                        },
                    },
                },
            },
            {
                "order": 3,
                "workflow": "folder_digest",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(in_dir)],
                    "output_dir": str(out_root / "step3"),
                    "parameters": {
                        "summary_length": 3,
                    },
                },
                "handoff": {"format": "markdown"},
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g07_e2e_pos")
    assert result.status == "executed"
    assert len(result.steps) == 3

    step2_json_path = out_root / "step2" / "g07_e2e_pos_02.medication-reconcile.json"
    assert step2_json_path.is_file()
    payload = json.loads(step2_json_path.read_text(encoding="utf-8"))
    assert payload["total_medications"] == 4
    assert payload["resolved_conflicts"] == 1
    notice = payload["medical_non_authority_notice"]
    assert "Medizinische Nichtautorität" in notice or "HINWEIS" in notice

    step2_md_path = out_root / "step2" / "g07_e2e_pos_02.medication-reconcile.md"
    assert step2_md_path.is_file()
    md_content = step2_md_path.read_text(encoding="utf-8")
    assert "# Konsolidierter Medikationsplan" in md_content
    assert "L-Thyroxin Henning" in md_content
    assert "Ramipril-ratiopharm" in md_content
    assert "Pantoprazol TAD" in md_content
    assert "Metformin HEXAL" in md_content
    assert "100 µg" in md_content
    assert "Dr. Weber telefonisch am 05.09.2026 bestätigt" in md_content

    # Step 3 digest check
    step3_report = RunLedger(
        Path(result.steps[2].ledger_path).parent
    ).load(result.steps[2].run_id)
    assert step3_report.status is RunStatus.EXECUTED


def test_g07_blocking_on_unresolved_dosage_conflict(tmp_path: Path) -> None:
    in_dir = tmp_path / "inputs_conflict"
    in_dir.mkdir(parents=True)
    (in_dir / "01_hausarzt.txt").write_text(DOC_HAUSARZT, encoding="utf-8")
    (in_dir / "02_klinik.txt").write_text(DOC_KLINIK, encoding="utf-8")

    out_root = tmp_path / "outputs_conflict"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))

    plan = {
        "voyage_id": "vy_g07_conflict",
        "title": "G07 Conflict Test Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(in_dir)],
                    "output_dir": str(out_root / "step1"),
                    "parameters": {
                        "column_template": "medication_plan",
                        "formats": ["md"],
                    },
                },
            },
            {
                "order": 2,
                "workflow": "medication_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "medication_reconcile",
                    "input_roots": [str(in_dir)],
                    "output_dir": str(out_root / "step2"),
                    "parameters": {
                        "formats": ["md"],
                        "min_medications": 1,
                        "require_unambiguous_dosages": True,
                        "application_domain": "medical_reports",
                        # NO user_corrections -> must block!
                    },
                },
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g07_e2e_conflict")
    assert result.status == "stopped"
    assert result.steps[1].status == "blocked"

    report = RunLedger(Path(result.steps[1].ledger_path).parent).load(result.steps[1].run_id)
    assert report.status is RunStatus.BLOCKED

    needs_input_path = out_root / "step2" / "g07_e2e_conflict_02.needs-user-input.json"
    assert needs_input_path.is_file()
    payload = json.loads(needs_input_path.read_text(encoding="utf-8"))
    questions = payload["questions"]
    assert any("L-Thyroxin" in q["prompt"] or "l-thyroxin" in q["field"] for q in questions)


def test_g07_blocking_on_missing_medication_fields(tmp_path: Path) -> None:
    in_dir = tmp_path / "inputs_missing"
    in_dir.mkdir(parents=True)
    (in_dir / "01_bad.txt").write_text(
        "Arzt: Dr. Weber\nMedikament: \nDosierung: \n", encoding="utf-8"
    )

    out_root = tmp_path / "outputs_missing"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))

    plan = {
        "voyage_id": "vy_g07_missing",
        "title": "G07 Missing Field Test",
        "steps": [
            {
                "order": 1,
                "workflow": "medication_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "medication_reconcile",
                    "input_roots": [str(in_dir)],
                    "output_dir": str(out_root / "step1"),
                    "parameters": {
                        "formats": ["md"],
                        "min_medications": 1,
                    },
                },
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g07_e2e_missing")
    assert result.status == "stopped"
    assert result.steps[0].status == "blocked"


def test_g07_blocking_on_insufficient_medications(tmp_path: Path) -> None:
    in_dir = tmp_path / "inputs_few"
    in_dir.mkdir(parents=True)
    (in_dir / "01_one.txt").write_text(
        "Medikament: Aspirin\nDosierung: 100 mg\nEinnahme: 1-0-0-0\n",
        encoding="utf-8",
    )

    out_root = tmp_path / "outputs_few"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))

    plan = {
        "voyage_id": "vy_g07_few",
        "title": "G07 Few Meds Test",
        "steps": [
            {
                "order": 1,
                "workflow": "medication_reconcile",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "medication_reconcile",
                    "input_roots": [str(in_dir)],
                    "output_dir": str(out_root / "step1"),
                    "parameters": {
                        "formats": ["md"],
                        "min_medications": 5,  # Requires 5, only 1 present!
                    },
                },
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g07_e2e_few")
    assert result.status == "stopped"
    assert result.steps[0].status == "blocked"
