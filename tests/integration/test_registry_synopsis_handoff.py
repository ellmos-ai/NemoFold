"""A topic registry must select originals for a cited synopsis, not just pass JSON."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig
from nemofold.ledger import RunLedger
from nemofold.voyage_runs import _selected_registry_sources, run_voyage
from nemofold.voyages import VoyageStore


def _case(tmp_path: Path) -> dict:
    documents = tmp_path / "reports"
    documents.mkdir()
    (documents / "thyroid.txt").write_text(
        "Patient: Beispielperson\nFachrichtung: Endokrinologie\n"
        "Befund: Schilddrüse unauffällig.\n",
        encoding="utf-8",
    )
    (documents / "knee.txt").write_text(
        "Patient: Beispielperson\nFachrichtung: Orthopädie\n"
        "Befund: Knieverletzung.\n",
        encoding="utf-8",
    )
    return {
        "name": "Schilddrüse register to synopsis",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(documents)],
                    "output_dir": str(tmp_path / "out" / "01-register"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "medical_reports",
                        "topic_filter": ["Schilddrüse"],
                        "formats": ["md"],
                    },
                },
            },
            {
                "workflow": "synopsis_merge",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "synopsis_merge",
                    "input_roots": [str(documents)],
                    "output_dir": str(tmp_path / "out" / "02-synopsis"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"title": "Schilddrüse", "formats": ["md", "pdf"]},
                },
                "handoff": {"format": "document-registry", "mode": "selected_sources"},
            },
        ],
    }


def test_topic_registry_hands_only_selected_originals_to_synopsis(tmp_path: Path) -> None:
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    saved = store.save(_case(tmp_path))

    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="topic_bridge",
        base_dir=tmp_path,
    )

    assert result.status == "executed"
    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    edge = dossier["steps"][1]["handoff"]
    assert edge["schema"] == "nemofold.artifact-handoff.v1"
    assert edge["mode"] == "selected_sources"
    assert len(edge["selected_source_ids"]) == 1
    ledger = json.loads(Path(result.steps[1].ledger_path or "").read_text(encoding="utf-8"))
    assert ledger["coverage"]["total_sources"] == 1
    assert any(item["format"] == "pdf" for item in ledger["artifacts"])
    synopsis = (tmp_path / "out" / "02-synopsis" / "topic_bridge_02.synopsis.md")
    text = synopsis.read_text(encoding="utf-8")
    assert "Schilddrüse" in text
    assert "Knieverletzung" not in text


def test_empty_topic_selection_blocks_synopsis_before_it_runs(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["steps"][0]["job"]["parameters"]["topic_filter"] = ["Leber"]
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    saved = store.save(case)

    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="empty_topic",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert result.stopped_at == 2
    assert result.steps[1].status == "handoff_blocked"
    assert result.steps[1].errors == ("handoff_selection_empty",)
    assert not (tmp_path / "out" / "02-synopsis").exists()


def test_selected_original_changed_after_registry_is_not_reused(tmp_path: Path) -> None:
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    saved = store.save(_case(tmp_path))
    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="source_integrity",
        base_dir=tmp_path,
    )
    assert result.status == "executed"
    register_output = tmp_path / "out" / "01-register"
    receipt = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))[
        "steps"
    ][1]["handoff"]
    report = RunLedger(register_output / "ledger").load("source_integrity_01")
    (tmp_path / "reports" / "thyroid.txt").write_text(
        "Patient: Different bytes\nBefund: Schilddrüse.\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="handoff_source_hash_mismatch"):
        _selected_registry_sources(receipt, report, output_dir=str(register_output))


def test_declared_synopsis_cannot_hide_a_different_consumer_job(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["steps"][1]["job"]["workflow"] = "fact_distill"
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))

    with pytest.raises(ValueError, match="selected_sources requires.*synopsis_merge"):
        store.save(case)
