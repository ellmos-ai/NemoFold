"""G02: a fictional doctor folder must produce a traceable, scoped synopsis."""

from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
from dataclasses import replace
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

import nemofold.voyage_runs as voyage_runs
from nemofold.application import ExecutionConfig
from nemofold.document_extract import extract_document_text
from nemofold.job_io import load_job_snapshot
from nemofold.ledger import RunLedger
from nemofold.report_studio import _render_pdf
from nemofold.structured_sources import read_structured
from nemofold.voyage_runs import run_voyage
from nemofold.voyages import VoyageStore


def _write_scanned_body_pdf_with_selectable_footer(path: Path) -> None:
    """Write one text page plus a raster-body page whose footer alone is selectable."""
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(_render_pdf("Befund: Schilddrüse unauffällig.\n"))))
    page = writer.add_blank_page(width=595, height=842)
    image = DecodedStreamObject()
    image.set_data(bytes([0, 0, 0] * 4))
    image.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(2),
        NameObject("/Height"): NumberObject(2),
        NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
        NameObject("/BitsPerComponent"): NumberObject(8),
    })
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({
            NameObject("/Im0"): writer._add_object(image),
        }),
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): writer._add_object(font),
        }),
    })
    content = DecodedStreamObject()
    content.set_data(
        b"q 400 0 0 600 70 160 cm /Im0 Do Q "
        b"BT /F1 12 Tf 72 50 Td (Seite 2) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(path)


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
                        "require_complete_pdf_inventory": True,
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
    assert receipt["source_scope"]["require_complete_pdf_inventory"] is True
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
        "extractable_text_pages": 1,
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


def test_g02_declared_pdf_with_scanned_second_page_blocks_before_synopsis(
    tmp_path: Path,
) -> None:
    """Catches a scanned body passing because only its footer is selectable text."""
    reports = tmp_path / "fictional-doctor-folder"
    reports.mkdir()
    _write_scanned_body_pdf_with_selectable_footer(
        reports / "01-endokrinologie.pdf"
    )
    case = {
        "name": "G02 · scanned declared page",
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
                "handoff": {"format": "document-registry", "mode": "selected_sources"},
            },
        ],
    }
    saved = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),)).save(case)

    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="g02_scanned_page",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert len(result.steps) == 1
    assert result.steps[0].status == "blocked"
    assert result.steps[0].errors == (
        "expected_pdf_page_image_review_required:01-endokrinologie.pdf:page=2",
    )
    assert not (tmp_path / "out" / "register" / "g02_scanned_page_01.registry.json").exists()
    assert not (tmp_path / "out" / "synopsis").exists()


def test_g02_reviewed_scanned_page_flows_into_registry_and_synopsis(
    tmp_path: Path, monkeypatch,
) -> None:
    """A complete hash-bound transcript must become cited PDF evidence end to end."""
    reports = tmp_path / "fictional-doctor-folder"
    reports.mkdir()
    pdf = reports / "01-endokrinologie.pdf"
    _write_scanned_body_pdf_with_selectable_footer(pdf)
    source_sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
    reviewed_text = (
        "Patient: Fallperson 204\n"
        "Fachrichtung: Endokrinologie\n"
        "Befund: Schilddrüse vergrößert."
    )
    review = {
        "page": 2,
        "source_sha256": source_sha256,
        "method": "manual",
        "reviewer": "human:test-reviewer",
        "reviewed_at": "2026-09-16T07:50:00+02:00",
        "content_complete": True,
        "text": reviewed_text,
    }
    case = {
        "name": "G02 · reviewed scanned page",
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
                        "require_complete_pdf_inventory": True,
                        "pdf_page_reviews": {
                            "01-endokrinologie.pdf": [review],
                        },
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
                "handoff": {"format": "document-registry", "mode": "selected_sources"},
            },
        ],
    }
    saved = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),)).save(case)

    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="g02_reviewed_scan",
        base_dir=tmp_path,
    )

    assert result.status == "executed"
    receipt = result.steps[1].handoff or {}
    assert reviewed_text not in json.dumps(receipt, ensure_ascii=False)
    reviewed_pages = receipt["verified_pdf_pages"][0]["reviewed_pages"]
    assert reviewed_pages == [{
        "page": 2,
        "method": "manual",
        "reviewer": "human:test-reviewer",
        "reviewed_at": "2026-09-16T07:50:00+02:00",
        "content_complete": True,
        "text_sha256": hashlib.sha256(reviewed_text.encode("utf-8")).hexdigest(),
    }]
    consumer = load_job_snapshot(
        tmp_path / "out" / "synopsis" / "jobs" / "g02_reviewed_scan_02.json"
    )
    assert len(consumer.parameters["source_page_reviews"]) == 1
    assert next(iter(consumer.parameters["source_page_reviews"].values())) == [review]
    registry = json.loads((
        tmp_path / "out" / "register" / "g02_reviewed_scan_01.registry.json"
    ).read_text(encoding="utf-8"))
    synopsis = (
        tmp_path / "out" / "synopsis" / "g02_reviewed_scan_02.synopsis.md"
    ).read_text(encoding="utf-8")
    finding = next(
        cell for cell in registry["rows"][0]["cells"]
        if cell["column"] == "Befund"
    )
    assert finding["value"] == "Schilddrüse unauffällig."
    assert "Schilddrüse vergrößert" in synopsis

    original_run_job = voyage_runs.run_job

    def run_with_tampered_review(job, *args, **kwargs):
        if job.workflow == "synopsis_merge" and job.parameters.get(
            "source_page_reviews"
        ):
            parameters = json.loads(json.dumps(job.parameters))
            reviews = next(iter(parameters["source_page_reviews"].values()))
            reviews[0]["text"] = "Befund: manipulierte Übergabe."
            job = replace(job, parameters=parameters)
        return original_run_job(job, *args, **kwargs)

    monkeypatch.setattr(voyage_runs, "run_job", run_with_tampered_review)
    tampered = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="g02_reviewed_scan_tampered",
        base_dir=tmp_path,
    )

    assert tampered.status == "stopped"
    assert tampered.steps[1].status == "handoff_invalidated"
    assert tampered.steps[1].errors == ("handoff_consumer_source_mismatch",)


def test_g02_complete_pdf_inventory_blocks_an_undeclared_report(tmp_path: Path) -> None:
    reports = tmp_path / "fictional-doctor-folder"
    reports.mkdir()
    (reports / "01-endokrinologie.pdf").write_bytes(
        _render_pdf("Patient: Fallperson 204\nBefund: Schilddrüse unauffällig.\n")
    )
    (reports / "02-undeclared.pdf").write_bytes(
        _render_pdf("Patient: Fallperson 204\nBefund: Schilddrüse vergrößert.\n")
    )
    case = {
        "name": "G02 · complete PDF inventory",
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
                        "expected_pdf_pages": {"01-endokrinologie.pdf": 1},
                        "require_complete_pdf_inventory": True,
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
                "handoff": {"format": "document-registry", "mode": "selected_sources"},
            },
        ],
    }
    saved = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),)).save(case)

    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="g02_undeclared_pdf",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert result.steps[0].errors == (
        "expected_pdf_source_undeclared:02-undeclared.pdf",
    )
    assert not (tmp_path / "out" / "register" / "g02_undeclared_pdf_01.registry.json").exists()
    assert not (tmp_path / "out" / "synopsis").exists()


def test_g02_handoff_rechecks_for_a_pdf_added_after_the_producer(
    tmp_path: Path, monkeypatch,
) -> None:
    reports = tmp_path / "fictional-doctor-folder"
    reports.mkdir()
    (reports / "01-endokrinologie.pdf").write_bytes(
        _render_pdf("Patient: Fallperson 204\nBefund: Schilddrüse unauffällig.\n")
    )
    case = {
        "name": "G02 · late PDF",
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
                        "expected_pdf_pages": {"01-endokrinologie.pdf": 1},
                        "require_complete_pdf_inventory": True,
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
                "handoff": {"format": "document-registry", "mode": "selected_sources"},
            },
        ],
    }
    saved = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),)).save(case)
    original = voyage_runs._selected_registry_sources

    def add_late_pdf(*args, **kwargs):
        (reports / "02-late.pdf").write_bytes(
            _render_pdf("Patient: Fallperson 204\nBefund: Schilddrüse vergrößert.\n")
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(voyage_runs, "_selected_registry_sources", add_late_pdf)

    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="g02_late_pdf",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert result.steps[0].status == "executed"
    assert result.steps[1].status == "handoff_blocked"
    assert result.steps[1].errors == (
        "handoff_expected_pdf_source_undeclared:02-late.pdf",
    )
    assert not (tmp_path / "out" / "synopsis").exists()
