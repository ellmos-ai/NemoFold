"""G02: a fictional doctor folder must produce a traceable, scoped synopsis."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from pypdf import PdfReader

from nemofold.application import ExecutionConfig
from nemofold.document_extract import extract_document_text
from nemofold.job_io import load_job_snapshot
from nemofold.ledger import RunLedger
from nemofold.report_studio import _render_pdf
from nemofold.structured_sources import read_structured
from nemofold.voyage_runs import run_voyage
from nemofold.voyages import VoyageStore


def test_g02_fictional_doctor_folder_has_cited_pdf_and_verified_handoff(
    tmp_path: Path,
) -> None:
    """Catches a silent source widening, lost report, or receipt/PDF disconnect."""
    reports = tmp_path / "fictional-doctor-folder"
    reports.mkdir()
    (reports / "01-endokrinologie.pdf").write_bytes(
        _render_pdf(
            "# Tabelle bericht\nPatient: Fallperson 204\n"
            "Fachrichtung: Endokrinologie\n"
            "Befund: Schilddrüse unauffällig.\n"
        )
    )
    (reports / "02-orthopaedie.txt").write_text(
        "Patient: Fallperson 204\nFachrichtung: Orthopädie\n"
        "Befund: Knieverletzung.\n",
        encoding="utf-8",
    )
    database = reports / "03-verlauf.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE bericht ("Befund" TEXT)')
        connection.execute(
            'INSERT INTO bericht VALUES (?)', ("Schilddrüse vergrößert",)
        )
        connection.execute(
            'INSERT INTO bericht VALUES (?)', ("Leberwert auffällig",)
        )

    case = {
        "name": "G02 · fiktive Arztberichte",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(reports)],
                    "output_dir": str(tmp_path / "out" / "register"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "medical_reports",
                        "topic_filter": ["Schilddrüse"],
                        "source_tables": ["bericht"],
                        "expected_pdf_pages": {"01-endokrinologie.pdf": 1},
                        "formats": ["md"],
                    },
                },
            },
            {
                "workflow": "synopsis_merge",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "synopsis_merge",
                    "input_roots": [str(reports)],
                    "output_dir": str(tmp_path / "out" / "synopsis"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "title": "Schilddrüse · fiktiver Verlauf",
                        "formats": ["md", "pdf"],
                    },
                },
                "handoff": {
                    "format": "document-registry",
                    "mode": "selected_sources",
                },
            },
        ],
    }
    saved = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),)).save(case)
    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="g02_doctor_folder",
        base_dir=tmp_path,
    )

    assert result.status == "executed"
    assert [step.run_id for step in result.steps] == [
        "g02_doctor_folder_01", "g02_doctor_folder_02"
    ]
    assert all(step.ledger_path and Path(step.ledger_path).is_file()
               for step in result.steps)
    receipt = result.steps[1].handoff or {}
    assert receipt["schema"] == "nemofold.artifact-handoff.v1"
    assert receipt["status"] == "verified"
    assert receipt["source_scope"]["source_tables"] == ["bericht"]
    assert receipt["application_domain"] == "medical_reports"
    assert len(receipt["source_lineage"]) == 2
    assert {Path(item["path"]).name for item in receipt["source_lineage"]} == {
        "01-endokrinologie.pdf", "03-verlauf.sqlite"
    }
    assert all(
        hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
        == item["sha256"]
        for item in receipt["source_lineage"]
    )
    assert len(receipt["selected_source_lines"]) == 1
    assert receipt["verified_pdf_pages"] == [{
        "producer_source_id": next(
            item["producer_source_id"] for item in receipt["source_lineage"]
            if item["path"].endswith("01-endokrinologie.pdf")
        ),
        "display_name": "01-endokrinologie.pdf",
        "sha256": hashlib.sha256(
            (reports / "01-endokrinologie.pdf").read_bytes()
        ).hexdigest(),
        "expected_pages": 1,
        "physical_pages": 1,
    }]
    snapshot = load_job_snapshot(
        tmp_path / "out" / "synopsis" / "jobs" / "g02_doctor_folder_02.json"
    )
    assert {source.source_id for source in snapshot.sources} == {
        item["consumer_source_id"] for item in receipt["source_lineage"]
    }
    assert snapshot.parameters["application_domain"] == "medical_reports"
    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    assert dossier["steps"][1]["handoff"] == receipt
    report = RunLedger(tmp_path / "out" / "synopsis" / "ledger").load(
        "g02_doctor_folder_02"
    )
    assert report.coverage.total_sources == 2
    assert report.metadata["conflicts"] >= 1
    assert report.metadata["application_domain"] == "medical_reports"
    assert "keine medizinische Diagnose" in (
        tmp_path / "out" / "synopsis" / "g02_doctor_folder_02.synopsis.md"
    ).read_text(encoding="utf-8")
    pdf = tmp_path / "out" / "synopsis" / "g02_doctor_folder_02_synopsis.pdf"
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(pdf).pages)
    assert "Schilddrüse unauffällig" in pdf_text
    assert "Schilddrüse vergrößert" in pdf_text
    assert "keine medizinische Diagnose" in pdf_text
    assert "Knieverletzung" not in pdf_text
    assert "Leberwert auffällig" not in pdf_text
    assert any(
        artifact.format == "pdf"
        and artifact.sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest()
        for artifact in report.artifacts
    )
    evidence = next(
        Path(artifact.path).read_text(encoding="utf-8")
        for artifact in report.artifacts if artifact.format == "markdown"
    )
    source_texts = {
        item["consumer_source_id"]: (
            read_structured(item["path"], tables=("bericht",)).text
            if item["path"].endswith(".sqlite")
            else extract_document_text(item["path"])
        )
        for item in receipt["source_lineage"]
    }
    locators = [
        (
            match.group(1), int(match.group(2)), match.group(3),
            match.group(0).removeprefix("- "),
        )
        for line in evidence.splitlines()
        if (match := re.match(
            r'^- \[([^,\]]+), section line (\d+)\] "(.*)"$', line
        ))
    ]
    assert len(locators) >= 4
    assert {source_id for source_id, _, _, _ in locators} == set(source_texts)
    assert {"Schilddrüse unauffällig.", "Schilddrüse vergrößert"} <= {
        quote for _, _, quote, _ in locators
    }
    assert all(
        0 < line_number <= len(source_texts[source_id].splitlines())
        and quote in source_texts[source_id].splitlines()[line_number - 1]
        for source_id, line_number, quote, _ in locators
    )
    assert all(locator in pdf_text for _, _, _, locator in locators)
    assert report.coverage.read_sources == report.coverage.cited_sources == 2


def test_g02_missing_expected_pdf_page_blocks_before_synopsis(tmp_path: Path) -> None:
    """Catches a one-page PDF against an explicit two-page source declaration."""
    reports = tmp_path / "fictional-doctor-folder"
    reports.mkdir()
    (reports / "01-endokrinologie.pdf").write_bytes(
        _render_pdf(
            "Patient: Fallperson 204\n"
            "Befund: Schilddrüse unauffällig.\n"
        )
    )
    case = {
        "name": "G02 · expected page absent",
        "steps": [
            {
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(reports)],
                    "output_dir": str(tmp_path / "out" / "register"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "medical_reports",
                        "topic_filter": ["Schilddrüse"],
                        "expected_pdf_pages": {"01-endokrinologie.pdf": 2},
                        "formats": ["md"],
                    },
                },
            },
            {
                "workflow": "synopsis_merge",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "synopsis_merge",
                    "input_roots": [str(reports)],
                    "output_dir": str(tmp_path / "out" / "synopsis"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"title": "Schilddrüse", "formats": ["md", "pdf"]},
                },
                "handoff": {
                    "format": "document-registry",
                    "mode": "selected_sources",
                },
            },
        ],
    }
    saved = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),)).save(case)

    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="g02_missing_page",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert len(result.steps) == 1
    assert result.steps[0].status == "blocked"
    assert result.steps[0].errors == (
        "expected_pdf_page_gap:01-endokrinologie.pdf",
    )
    assert not (tmp_path / "out" / "register" / "g02_missing_page_01.registry.json").exists()
    assert not (tmp_path / "out" / "synopsis").exists()
