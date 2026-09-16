"""A topic registry must select originals for a cited synopsis, not just pass JSON."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import nemofold.application as application
import nemofold.voyage_runs as voyage_runs
from nemofold.application import ExecutionConfig
from nemofold.job_io import load_job_snapshot
from nemofold.ledger import RunLedger
from nemofold.voyage_runs import (
    _selected_registry_sources,
    run_voyage,
    voyage_run_payload,
)
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


def test_two_selected_reports_keep_a_verifiable_source_lineage(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (tmp_path / "reports" / "thyroid_followup.txt").write_text(
        "Patient: Beispielperson\nFachrichtung: Endokrinologie\n"
        "Befund: Schilddrüse vergrößert.\n",
        encoding="utf-8",
    )
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    saved = store.save(case)

    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="two_reports",
        base_dir=tmp_path,
    )

    assert result.status == "executed"
    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    edge = dossier["steps"][1]["handoff"]
    lineage = edge["source_lineage"]
    assert len(lineage) == 2
    assert {item["producer_source_id"] for item in lineage} == set(
        edge["selected_source_ids"]
    )
    assert all(item["sha256"] == edge["selected_source_sha256"][item["producer_source_id"]]
               for item in lineage)
    snapshot = load_job_snapshot(tmp_path / "out" / "02-synopsis" / "jobs" / "two_reports_02.json")
    assert {item["consumer_source_id"] for item in lineage} == {
        source.source_id for source in snapshot.sources
    }
    synopsis = (tmp_path / "out" / "02-synopsis" / "two_reports_02.synopsis.md").read_text(
        encoding="utf-8"
    )
    assert "Schilddrüse unauffällig" in synopsis
    assert "Schilddrüse vergrößert" in synopsis
    assert "Knieverletzung" not in synopsis
    assert "Conflicts" in synopsis


def test_structured_doctor_report_crosses_registry_to_synopsis_with_receipt(
    tmp_path: Path,
) -> None:
    from nemofold.delivery import workbook_bytes

    case = _case(tmp_path)
    workbook = tmp_path / "reports" / "thyroid_table.xlsx"
    workbook.write_bytes(
        workbook_bytes(
            ("Patient", "Fachrichtung", "Befund"),
            (("Beispielperson", "Endokrinologie", "Schilddrüse vergrößert"),),
        )
    )
    saved = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),)).save(case)
    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="structured_report_bridge",
        base_dir=tmp_path,
    )

    assert result.status == "executed"
    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    edge = dossier["steps"][1]["handoff"]
    assert edge["status"] == "verified"
    assert len(edge["source_lineage"]) == 2
    assert edge["selected_source_sha256"]
    assert all(item["sha256"] == edge["selected_source_sha256"][item["producer_source_id"]]
               for item in edge["source_lineage"])
    synopsis = (
        tmp_path / "out" / "02-synopsis" / "structured_report_bridge_02.synopsis.md"
    ).read_text(encoding="utf-8")
    assert "Schilddrüse unauffällig" in synopsis
    assert "Schilddrüse vergrößert" in synopsis
    assert "Knieverletzung" not in synopsis
    ledger = json.loads(Path(result.steps[1].ledger_path or "").read_text(encoding="utf-8"))
    assert ledger["coverage"]["total_sources"] == 2
    assert any(item["format"] == "pdf" for item in ledger["artifacts"])


def test_structured_omissions_survive_registry_to_synopsis_ledgers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nemofold.delivery import workbook_bytes

    case = _case(tmp_path)
    workbook = tmp_path / "reports" / "thyroid_table.xlsx"
    workbook.write_bytes(
        workbook_bytes(
            ("Befund",),
            (
                ("Schilddrüse vergrößert",),
                ("Schilddrüse stabil",),
                ("Leberwert auffällig",),
            ),
        )
    )
    original_read = application.read_structured

    def limited_reader(path, **kwargs):
        return original_read(path, max_rows=2, **kwargs)

    monkeypatch.setattr(application, "read_structured", limited_reader)
    saved = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),)).save(case)
    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="omission_bridge",
        base_dir=tmp_path,
    )

    assert result.status == "executed"
    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    for step in result.steps:
        ledger = json.loads(Path(step.ledger_path or "").read_text(encoding="utf-8"))
        assert any(
            "1 row(s) beyond the ceiling of 2" in note
            for notes in ledger["metadata"]["source_read_notes"].values()
            for note in notes
        )
        assert dossier["steps"][step.order - 1]["source_read_notes"] == ledger["metadata"][
            "source_read_notes"
        ]
    markdown = (tmp_path / "out" / "voyage-dossier" / "omission_bridge.md")
    assert "source notes" in markdown.read_text(encoding="utf-8")
    response = voyage_run_payload(result, saved)
    assert response["steps"][1]["source_read_notes"] == dossier["steps"][1][
        "source_read_notes"
    ]
    synopsis = (tmp_path / "out" / "02-synopsis" / "omission_bridge_02.synopsis.md")
    assert "Leberwert auffällig" not in synopsis.read_text(encoding="utf-8")


def test_source_change_between_handoff_and_consumer_invalidates_the_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path)
    saved = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),)).save(case)
    original = voyage_runs.run_job

    def change_before_consumer(job, config, *, run_id):
        if job.workflow == "synopsis_merge":
            (tmp_path / "reports" / "thyroid.txt").write_text(
                "Patient: Beispielperson\nBefund: Schilddrüse plötzlich verändert.\n",
                encoding="utf-8",
            )
        return original(job, config, run_id=run_id)

    monkeypatch.setattr(voyage_runs, "run_job", change_before_consumer)
    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="changed_mid_handoff",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert result.stopped_at == 2
    assert result.steps[1].status == "handoff_invalidated"
    assert result.steps[1].errors == ("handoff_consumer_source_mismatch",)
    assert result.steps[1].ledger_path is not None  # consumer did run; do not conceal it
    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    assert dossier["completed"] is False
    assert dossier["steps"][1]["handoff"]["status"] == "invalidated"


def test_temporary_change_during_extraction_cannot_enter_synopsis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),)).save(_case(tmp_path))
    target = tmp_path / "reports" / "thyroid.txt"
    original_bytes = target.read_bytes()
    original_extract = application.extract_document_text
    target_reads = 0

    def change_only_while_reading(path, **kwargs):
        nonlocal target_reads
        if Path(path).resolve() != target.resolve():
            return original_extract(path, **kwargs)
        target_reads += 1
        if target_reads == 1:  # registry producer still reads the original bytes
            return original_extract(path, **kwargs)
        target.write_text("Befund: Schilddrüse plötzlich verändert.\n", encoding="utf-8")
        try:
            return original_extract(path, **kwargs)
        finally:
            target.write_bytes(original_bytes)

    monkeypatch.setattr(application, "extract_document_text", change_only_while_reading)
    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="changed_during_extract",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert result.steps[1].status == "failed"
    assert "source_hash_mismatch" in result.steps[1].errors[0]
    assert not (tmp_path / "out" / "02-synopsis" / "changed_during_extract_02.synopsis.md").exists()


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
