"""End-to-end and unit tests for Gate G11: OCR and Knowledge Index Pipeline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nemofold.application import ExecutionConfig
from nemofold.ocr_pipeline import (
    DEFAULT_MIN_CONFIDENCE,
    OCR_GROUNDING_NOTICE,
    assess_page_ocr,
)
from nemofold.pdf_page_expectations import PdfPageReview
from nemofold.report_studio import _render_pdf
from nemofold.voyage_runs import run_voyage


def test_assess_page_ocr_native_text() -> None:
    res = assess_page_ocr(
        page_num=1,
        raw_text="Laborbericht Befund",
        has_raster_images=False,
        expected_sha256="abc",
        page_reviews={},
        min_confidence=0.70,
    )
    assert res.method == "native_text"
    assert res.confidence == 1.0
    assert not res.needs_review
    assert res.text == "Laborbericht Befund"


def test_assess_page_ocr_with_review() -> None:
    sha = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    review = PdfPageReview(
        page=1,
        source_sha256=sha,
        method="ocr",
        reviewer="Dr. Schmidt",
        reviewed_at="2026-09-16T12:00:00Z",
        content_complete=True,
        text="Geprüfter Scan-Text",
    )
    res = assess_page_ocr(
        page_num=1,
        raw_text="",
        has_raster_images=True,
        expected_sha256=sha,
        page_reviews={1: review},
        min_confidence=0.70,
    )
    assert res.method == "ocr"
    assert res.confidence >= 0.70
    assert not res.needs_review
    assert res.text == "Geprüfter Scan-Text"


def test_assess_page_ocr_low_quality_unreviewed() -> None:
    res = assess_page_ocr(
        page_num=1,
        raw_text="",
        has_raster_images=True,
        expected_sha256="abc",
        page_reviews={},
        min_confidence=0.70,
        synthetic_ocr_text="??? ###",
        synthetic_confidence=0.35,
    )
    assert res.method == "ocr"
    assert res.confidence == 0.35
    assert res.needs_review


def test_g11_positive_voyage(tmp_path: Path) -> None:
    inbox = tmp_path / "inputs"
    inbox.mkdir(parents=True, exist_ok=True)
    out_step1 = tmp_path / "out_step1"
    out_step2 = tmp_path / "out_step2"
    out_step3 = tmp_path / "out_step3"

    f1 = inbox / "01-labor.pdf"
    f1.write_bytes(
        _render_pdf(
            "Laborbefund Endokrinologie:\n"
            "Patientin: Anna Schmidt\n"
            "Schilddrüsen-Laborwerte: TSH 1.4 mU/l, fT3 3.1 pg/ml, fT4 1.2 ng/dl.\n"
            "Beurteilung: Euthyreote Stoffwechsellage.\n"
        )
    )

    f2 = inbox / "02-scan.pdf"
    f2.write_bytes(
        _render_pdf(
            "Arztbrief Nuklearmedizin:\n"
            "Patientin: Anna Schmidt\n"
            "Befund: Sonographie Schilddrüse zeigt knotige Veränderung rechts.\n"
            "Empfehlung: Kontrolluntersuchung in 6 Monaten.\n"
        )
    )

    f3 = inbox / "03-leitlinie.txt"
    f3.write_text(
        "Leitlinie Schilddrüsen-Knoten: Diagnostik und Verlaufskontrolle bei Struma nodosa.\n",
        encoding="utf-8",
    )

    f4 = inbox / "04-labor-duplikat.pdf"
    f4.write_bytes(f1.read_bytes())

    f2_sha = hashlib.sha256(f2.read_bytes()).hexdigest()

    plan = {
        "voyage_id": "vy_g11_test_pos",
        "title": "G11 Positive Test Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(inbox)],
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
                "workflow": "ocr_pipeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "ocr_pipeline",
                    "input_roots": [str(inbox)],
                    "output_dir": str(out_step2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "min_confidence": DEFAULT_MIN_CONFIDENCE,
                        "detect_duplicates": True,
                        "test_query": "Schilddrüse",
                        "require_retrieval": True,
                        "formats": ["md", "json"],
                        "page_reviews": {
                            "02-scan.pdf": [
                                {
                                    "page": 1,
                                    "source_sha256": f2_sha,
                                    "method": "ocr",
                                    "reviewer": "Dr. Weber",
                                    "reviewed_at": "2026-09-16T10:00:00Z",
                                    "content_complete": True,
                                    "text": (
                                        "Arztbrief Nuklearmedizin: Sonographie Schilddrüse "
                                        "zeigt knotige Veränderung rechts."
                                    ),
                                }
                            ]
                        },
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

    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(plan, config, run_id="g11_pos_test")
    assert result.status == "executed"
    assert len(result.steps) == 3

    step2 = result.steps[1]
    step2_dir = Path(step2.output_dir)
    json_path = step2_dir / f"{step2.run_id}.ocr-pipeline.json"
    md_path = step2_dir / f"{step2.run_id}.ocr-pipeline.md"

    assert json_path.is_file()
    assert md_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["indexed_documents"] >= 2
    assert payload["duplicate_documents"] >= 1
    assert payload["mean_confidence"] >= DEFAULT_MIN_CONFIDENCE
    assert payload["retrieval_probe"]["verified"] is True
    assert payload["retrieval_probe"]["hits"] >= 1

    md_content = md_path.read_text(encoding="utf-8")
    assert OCR_GROUNDING_NOTICE in md_content
    assert "Schilddrüse" in md_content


def test_g11_negative_low_ocr_quality_blocked(tmp_path: Path) -> None:
    inbox = tmp_path / "inputs_low"
    inbox.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "out_low"

    bad_scan = inbox / "scan-schlecht.pdf"
    bad_scan.write_bytes(_render_pdf("Schlecht lesbarer Scan mit Artefakten.\n"))

    plan = {
        "voyage_id": "vy_g11_test_low",
        "title": "G11 Negative Low Quality Test Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "ocr_pipeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "ocr_pipeline",
                    "input_roots": [str(inbox)],
                    "output_dir": str(out_dir),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "min_confidence": 0.70,
                        "synthetic_ocr_map": {
                            "scan-schlecht.pdf:1": ("?? %%%", 0.35)
                        },
                    },
                },
            }
        ],
    }

    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(plan, config, run_id="g11_low_test")
    assert result.status == "stopped"
    assert result.steps[0].status == "blocked"

    needs_input = out_dir / f"{result.steps[0].run_id}.needs-user-input.json"
    assert needs_input.is_file()
    payload = json.loads(needs_input.read_text(encoding="utf-8"))
    assert any("ocr_review" in q["field"] for q in payload.get("questions", []))


def test_g11_negative_corrupted_scan_blocked(tmp_path: Path) -> None:
    inbox = tmp_path / "inputs_corrupt"
    inbox.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "out_corrupt"

    corrupted = inbox / "bad.pdf"
    corrupted.write_bytes(b"%PDF-1.4\nTRUNCATED_CRAP\x00\xff")

    plan = {
        "voyage_id": "vy_g11_test_corrupt",
        "title": "G11 Negative Corrupt Test Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "ocr_pipeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "ocr_pipeline",
                    "input_roots": [str(inbox)],
                    "output_dir": str(out_dir),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {},
                },
            }
        ],
    }

    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(plan, config, run_id="g11_corrupt_test")
    assert result.status == "stopped"
    assert result.steps[0].status == "blocked"


def test_g11_negative_retrieval_fail_blocked(tmp_path: Path) -> None:
    inbox = tmp_path / "inputs_retrieval_fail"
    inbox.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "out_retrieval_fail"

    doc = inbox / "unrelated.txt"
    doc.write_text("Text ueber Teilchenphysik und Quantenmechanik.\n", encoding="utf-8")

    plan = {
        "voyage_id": "vy_g11_test_retrieval_fail",
        "title": "G11 Negative Retrieval Fail Test Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "ocr_pipeline",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "ocr_pipeline",
                    "input_roots": [str(inbox)],
                    "output_dir": str(out_dir),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "test_query": "Schilddrüse",
                        "require_retrieval": True,
                    },
                },
            }
        ],
    }

    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(plan, config, run_id="g11_retrieval_test")
    assert result.status == "stopped"
    assert result.steps[0].status == "blocked"
