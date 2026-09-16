"""G03: document intake recognition, classification, index synchronization and blocking paths."""

from __future__ import annotations

import json
from pathlib import Path

from nemofold.application import ExecutionConfig
from nemofold.contracts import SourceRecord
from nemofold.document_index import DocumentIndex
from nemofold.inventory import _stable_source_id
from nemofold.voyage_runs import run_voyage


def test_g03_document_intake_classifies_and_synchronizes_index(tmp_path: Path) -> None:
    """Intake recognizes new/updated documents, routes them into categories, and updates index."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    patient_target = tmp_path / "targets" / "patient"
    patient_target.mkdir(parents=True)
    wissen_target = tmp_path / "targets" / "wissen"
    wissen_target.mkdir(parents=True)

    # 1. Patient befund (will be updated vs pre-seeded index)
    doc1 = inbox / "01-arztbrief-mueller.txt"
    doc1.write_text(
        "Arztbrief Praxis Dr. Weber\nPatient: Max Mueller\n"
        "Befund: Sonographie der Schilddruese ohne pathologischen Befund.\n"
        "Diagnose: Euthyreote Struma nodosa.\n",
        encoding="utf-8",
    )

    # 2. Fachwissen (new document vs pre-seeded index)
    doc2 = inbox / "02-leitlinie-endokrinologie.txt"
    doc2.write_text(
        "Klinische Leitlinie Endokrinologie\n"
        "Thema: Leitlinie zur Diagnostik von Schilddruesenknoten.\n"
        "Evidenzbasierte Medizin fuer die Primaerversorgung.\n",
        encoding="utf-8",
    )

    # Pre-seed index with an old version of doc1 and an obsolete document
    db_dir = tmp_path / "outputs" / "smart_inbox" / "index"
    db_dir.mkdir(parents=True, exist_ok=True)
    index = DocumentIndex(db_dir / "nemofold.sqlite3")
    old_doc1_source = SourceRecord(
        source_id=_stable_source_id("root-0/01-arztbrief-mueller.txt"),
        path=str(doc1),
        display_name=doc1.name,
        sha256="old_obsolete_sha256_for_doc1",
        mime_type="text/plain",
        extraction_status="unchanged",
    )
    index.index_source(old_doc1_source, "Alter Befundtext vor der Aktualisierung")

    obsolete_path = inbox / "obsolete-geloeschtes-dokument.txt"
    old_obsolete_source = SourceRecord(
        source_id="src_obsolete_test_entry",
        path=str(obsolete_path),
        display_name="obsolete-geloeschtes-dokument.txt",
        sha256="obsolete_document_sha256",
        mime_type="text/plain",
        extraction_status="unchanged",
    )
    index.index_source(old_obsolete_source, "Dieses Dokument existiert nicht mehr im Ordner")
    index.close()

    case = {
        "name": "G03 · Dokumenteneingang und Index-Synchronisation",
        "steps": [
            {
                "workflow": "smart_inbox",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "smart_inbox",
                    "input_roots": [str(inbox)],
                    "target_roots": [str(patient_target), str(wissen_target)],
                    "output_dir": str(tmp_path / "outputs" / "smart_inbox"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "classification_policy": "content_categories",
                        "confidence_threshold": 0.25,
                        "maintain_index": True,
                        "allowed_extensions": [".txt"],
                        "original_policy": "move",
                        "routes": [
                            {
                                "suffixes": [".txt"],
                                "category": "patient",
                                "target_root": 0,
                                "match_terms": ["patient", "befund", "diagnose", "arztbrief"],
                            },
                            {
                                "suffixes": [".txt"],
                                "category": "wissen",
                                "target_root": 1,
                                "match_terms": ["leitlinie", "fachliteratur", "evidenz", "studie"],
                            },
                        ],
                    },
                },
            },
            {
                "workflow": "folder_digest",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(inbox)],
                    "output_dir": str(tmp_path / "outputs" / "digest"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "summary_length": 3,
                        "digest_depth": "full",
                    },
                },
                "handoff": {
                    "format": "action-plan",
                },
            },
        ],
    }

    config = ExecutionConfig(
        allowed_roots=(str(tmp_path),),
        apply_actions_allowed=True,
    )
    result = run_voyage(case, config=config, run_id="g03_test_positive", base_dir=tmp_path)

    assert result.status == "executed"
    assert len(result.steps) == 2

    step1 = result.steps[0]
    assert step1.status == "executed"

    step2 = result.steps[1]
    assert step2.status == "executed"
    assert step2.handoff is not None
    assert step2.handoff["format"] == "action-plan"
    assert step2.handoff["status"] == "verified"

    plan_path = Path(step1.output_dir) / f"{step1.run_id}.action-plan.json"
    plans = json.loads(plan_path.read_text(encoding="utf-8"))["plans"]
    assert len(plans) == 2

    # Verify classification categories
    plan_patient = next(p for p in plans if "01-arztbrief-mueller" in p["source"])
    plan_wissen = next(p for p in plans if "02-leitlinie-endokrinologie" in p["source"])
    assert plan_patient["category"] == "patient"
    assert plan_wissen["category"] == "wissen"

    # Verify index manifest artifact
    manifest_path = Path(step1.output_dir) / f"{step1.run_id}.index-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "nemofold.index-manifest.v1"
    # doc2 was new
    assert sum(1 for s in manifest["index_status"].values() if s == "indexed") == 1
    # doc1 was updated
    assert sum(1 for s in manifest["index_status"].values() if s == "updated") == 1
    # obsolete was pruned
    assert manifest["pruned_source_ids"] == ["src_obsolete_test_entry"]


def test_g03_unreadable_document_blocks_before_action(tmp_path: Path) -> None:
    """Corrupt / unreadable input stops execution fail-closed and produces a query artifact."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    target_patient = tmp_path / "targets" / "patient"
    target_patient.mkdir(parents=True, exist_ok=True)
    corrupt_file = inbox / "01-beschaedigter-scan.txt"
    # Null bytes triggering unreadable_input detection
    corrupt_file.write_bytes(b"BESCHAEDIGTER_SCAN\x00\x00\x00\n")

    case = {
        "name": "G03 · Unlesbares Dokument",
        "steps": [
            {
                "workflow": "smart_inbox",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "smart_inbox",
                    "input_roots": [str(inbox)],
                    "target_roots": [str(target_patient)],
                    "output_dir": str(tmp_path / "outputs" / "smart_inbox"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "classification_policy": "content_categories",
                        "routes": [
                            {
                                "suffixes": [".txt"],
                                "category": "patient",
                                "target_root": 0,
                                "match_terms": ["patient", "befund"],
                            }
                        ],
                    },
                },
            }
        ],
    }

    config = ExecutionConfig(
        allowed_roots=(str(tmp_path),),
        apply_actions_allowed=True,
    )
    result = run_voyage(case, config=config, run_id="g03_test_unreadable", base_dir=tmp_path)

    assert result.status == "stopped"
    assert result.stopped_at == 1
    step = result.steps[0]
    assert step.status == "blocked"
    assert step.errors == ("unreadable_input:01-beschaedigter-scan.txt",)

    # File was NOT moved or deleted
    assert corrupt_file.exists()

    # Needs user input artifact was written
    input_item = Path(step.output_dir) / f"{step.run_id}.needs-user-input.json"
    prompt = json.loads(input_item.read_text(encoding="utf-8"))
    assert prompt["schema"] == "nemofold.needs-user-input.v1"
    assert prompt["workflow"] == "smart_inbox"
    assert prompt["questions"][0]["field"] == "unreadable_01-beschaedigter-scan.txt"


def test_g03_unclassifiable_document_blocks_before_action(tmp_path: Path) -> None:
    """Unclassifiable input stops execution fail-closed and asks user for assignment."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    target_patient = tmp_path / "targets" / "patient"
    target_wissen = tmp_path / "targets" / "wissen"
    target_patient.mkdir(parents=True, exist_ok=True)
    target_wissen.mkdir(parents=True, exist_ok=True)
    unrelated_file = inbox / "01-kuchenrezept.txt"
    unrelated_file.write_text(
        "Zutaten fuer Apfelkuchen:\n250g Mehl, 125g Butter, 100g Zucker, 3 Aepfel.\n",
        encoding="utf-8",
    )

    case = {
        "name": "G03 · Unklassifizierbares Dokument",
        "steps": [
            {
                "workflow": "smart_inbox",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "smart_inbox",
                    "input_roots": [str(inbox)],
                    "target_roots": [
                        str(target_patient),
                        str(target_wissen),
                    ],
                    "output_dir": str(tmp_path / "outputs" / "smart_inbox"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "classification_policy": "content_categories",
                        "routes": [
                            {
                                "suffixes": [".txt"],
                                "category": "patient",
                                "target_root": 0,
                                "match_terms": ["patient", "befund", "arztbrief"],
                            },
                            {
                                "suffixes": [".txt"],
                                "category": "wissen",
                                "target_root": 1,
                                "match_terms": ["leitlinie", "studie", "fachliteratur"],
                            },
                        ],
                    },
                },
            }
        ],
    }

    config = ExecutionConfig(
        allowed_roots=(str(tmp_path),),
        apply_actions_allowed=True,
    )
    result = run_voyage(case, config=config, run_id="g03_test_unclassifiable", base_dir=tmp_path)

    assert result.status == "stopped"
    assert result.stopped_at == 1
    step = result.steps[0]
    assert step.status == "blocked"
    assert step.errors == ("unclassifiable_input:01-kuchenrezept.txt",)

    # File was untouched
    assert unrelated_file.exists()


def test_g03_ambiguous_document_blocks_before_action(tmp_path: Path) -> None:
    """Ambiguous document with conflicting matches stops execution and asks clarification."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    target_patient = tmp_path / "targets" / "patient"
    target_wissen = tmp_path / "targets" / "wissen"
    target_patient.mkdir(parents=True, exist_ok=True)
    target_wissen.mkdir(parents=True, exist_ok=True)
    mixed_file = inbox / "01-gemischter-text.txt"
    mixed_file.write_text(
        "Patient Max Mueller und Befund Arztbrief.\n"
        "Gleichzeitig Leitlinie Fachliteratur und Studie.\n",
        encoding="utf-8",
    )

    case = {
        "name": "G03 · Mehrdeutiges Dokument",
        "steps": [
            {
                "workflow": "smart_inbox",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "smart_inbox",
                    "input_roots": [str(inbox)],
                    "target_roots": [
                        str(target_patient),
                        str(target_wissen),
                    ],
                    "output_dir": str(tmp_path / "outputs" / "smart_inbox"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "classification_policy": "content_categories",
                        "routes": [
                            {
                                "suffixes": [".txt"],
                                "category": "patient",
                                "target_root": 0,
                                "match_terms": ["patient", "befund", "arztbrief"],
                            },
                            {
                                "suffixes": [".txt"],
                                "category": "wissen",
                                "target_root": 1,
                                "match_terms": ["leitlinie", "fachliteratur", "studie"],
                            },
                        ],
                    },
                },
            }
        ],
    }

    config = ExecutionConfig(
        allowed_roots=(str(tmp_path),),
        apply_actions_allowed=True,
    )
    result = run_voyage(case, config=config, run_id="g03_test_ambiguous", base_dir=tmp_path)

    assert result.status == "stopped"
    assert result.stopped_at == 1
    step = result.steps[0]
    assert step.status == "blocked"
    assert step.errors == ("ambiguous_classification:01-gemischter-text.txt",)

    # File was untouched
    assert mixed_file.exists()
