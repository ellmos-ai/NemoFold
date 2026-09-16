"""Explicit PDF page expectations must use the physical, hash-bound PDF count."""

from __future__ import annotations

import hashlib

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from nemofold.inventory import scan_paths
from nemofold.pdf_page_expectations import (
    PdfPageExpectationError,
    verify_pdf_page_expectations,
)
from nemofold.report_studio import _render_pdf


def test_zero_page_pdf_cannot_satisfy_one_expected_page(tmp_path) -> None:
    """Catches an empty extracted string masquerading as one split-text page."""
    writer = PdfWriter()
    writer.write(tmp_path / "zero.pdf")
    inventory = scan_paths((str(tmp_path),))

    with pytest.raises(
        PdfPageExpectationError, match="expected_pdf_page_gap:zero.pdf"
    ):
        verify_pdf_page_expectations(
            inventory.records, {"zero.pdf": 1}
        )


def test_extra_physical_page_has_a_distinct_block_reason(tmp_path) -> None:
    """Catches an unapproved extra page being mislabeled as an absent page."""
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=595, height=842)
    writer.write(tmp_path / "extra.pdf")
    inventory = scan_paths((str(tmp_path),))

    with pytest.raises(
        PdfPageExpectationError, match="expected_pdf_page_extra:extra.pdf"
    ):
        verify_pdf_page_expectations(
            inventory.records, {"extra.pdf": 1}
        )


def test_matching_physical_page_without_extractable_text_requires_review(tmp_path) -> None:
    """Catches an image-only or blank page passing a physical-count check."""
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(tmp_path / "image-only.pdf")
    inventory = scan_paths((str(tmp_path),))

    with pytest.raises(
        PdfPageExpectationError,
        match="expected_pdf_page_text_missing:image-only.pdf:page=1",
    ):
        verify_pdf_page_expectations(
            inventory.records, {"image-only.pdf": 1}
        )


def test_raster_body_with_selectable_footer_requires_image_review(tmp_path) -> None:
    """Catches a scanned report body passing because only its footer is text."""
    writer = PdfWriter()
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
        b"BT /F1 12 Tf 72 50 Td (Seite 1) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(tmp_path / "scanned-body.pdf")
    reader_page = PdfReader(tmp_path / "scanned-body.pdf").pages[0]
    assert "Seite 1" in (reader_page.extract_text() or "")
    assert len(reader_page.images) == 1
    inventory = scan_paths((str(tmp_path),))

    with pytest.raises(
        PdfPageExpectationError,
        match="expected_pdf_page_image_review_required:scanned-body.pdf:page=1",
    ):
        verify_pdf_page_expectations(
            inventory.records, {"scanned-body.pdf": 1}
        )


def test_hash_bound_complete_manual_review_releases_and_summarizes_image_page(
    tmp_path,
) -> None:
    """A reviewed transcript must replace the incomplete native page text."""
    writer = PdfWriter()
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
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({
            NameObject("/Im0"): writer._add_object(image),
        }),
    })
    content = DecodedStreamObject()
    content.set_data(b"q 400 0 0 600 70 160 cm /Im0 Do Q")
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(tmp_path / "reviewed.pdf")
    inventory = scan_paths((str(tmp_path),))
    source = inventory.records[0]

    checks = verify_pdf_page_expectations(
        inventory.records,
        {"reviewed.pdf": 1},
        page_reviews={
            "reviewed.pdf": [{
                "page": 1,
                "source_sha256": source.sha256,
                "method": "manual",
                "reviewer": "human:test-reviewer",
                "reviewed_at": "2026-09-16T07:50:00+02:00",
                "content_complete": True,
                "text": "Befund: Schilddrüse vergrößert.",
            }],
        },
    )

    assert len(checks) == 1
    assert checks[0].reviewed_pages[0].text == "Befund: Schilddrüse vergrößert."
    assert checks[0].as_payload()["reviewed_pages"] == [{
        "page": 1,
        "method": "manual",
        "reviewer": "human:test-reviewer",
        "reviewed_at": "2026-09-16T07:50:00+02:00",
        "content_complete": True,
        "text_sha256": hashlib.sha256(
            "Befund: Schilddrüse vergrößert.".encode()
        ).hexdigest(),
    }]


def test_pdf_page_review_is_rejected_when_bound_to_other_source_bytes(tmp_path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(tmp_path / "reviewed.pdf")
    inventory = scan_paths((str(tmp_path),))

    with pytest.raises(
        PdfPageExpectationError,
        match="expected_pdf_page_review_source_mismatch:reviewed.pdf:page=1",
    ):
        verify_pdf_page_expectations(
            inventory.records,
            {"reviewed.pdf": 1},
            page_reviews={
                "reviewed.pdf": [{
                    "page": 1,
                    "source_sha256": "0" * 64,
                    "method": "ocr",
                    "reviewer": "ocr:test-engine",
                    "reviewed_at": "2026-09-16T07:50:00+02:00",
                    "content_complete": True,
                    "text": "Befund: Schilddrüse unauffällig.",
                }],
            },
        )


def test_pdf_page_review_cannot_override_a_complete_native_text_page(tmp_path) -> None:
    (tmp_path / "native.pdf").write_bytes(_render_pdf("Befund: Originaltext."))
    inventory = scan_paths((str(tmp_path),))
    source = inventory.records[0]
    reviews = {
        "native.pdf": [{
            "page": 1,
            "source_sha256": source.sha256,
            "method": "manual",
            "reviewer": "human:test-reviewer",
            "reviewed_at": "2026-09-16T07:50:00+02:00",
            "content_complete": True,
            "text": "Befund: überschrieben.",
        }],
    }

    with pytest.raises(
        PdfPageExpectationError,
        match="expected_pdf_page_review_unneeded:native.pdf:page=1",
    ):
        verify_pdf_page_expectations(
            inventory.records, {"native.pdf": 1}, page_reviews=reviews
        )


def test_every_incomplete_page_needs_its_own_review(tmp_path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=595, height=842)
    writer.write(tmp_path / "two-blank-pages.pdf")
    inventory = scan_paths((str(tmp_path),))
    source = inventory.records[0]

    with pytest.raises(
        PdfPageExpectationError,
        match="expected_pdf_page_text_missing:two-blank-pages.pdf:page=2",
    ):
        verify_pdf_page_expectations(
            inventory.records,
            {"two-blank-pages.pdf": 2},
            page_reviews={
                "two-blank-pages.pdf": [{
                    "page": 1,
                    "source_sha256": source.sha256,
                    "method": "manual",
                    "reviewer": "human:test-reviewer",
                    "reviewed_at": "2026-09-16T07:50:00+02:00",
                    "content_complete": True,
                    "text": "Seite 1 wurde vollständig geprüft.",
                }],
            },
        )


def test_complete_pdf_inventory_rejects_an_undeclared_pdf(tmp_path) -> None:
    """A complete-folder claim cannot silently omit another PDF in the same input."""
    for name in ("declared.pdf", "undeclared.pdf"):
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.write(tmp_path / name)
    inventory = scan_paths((str(tmp_path),))

    with pytest.raises(
        PdfPageExpectationError,
        match="expected_pdf_source_undeclared:undeclared.pdf",
    ):
        verify_pdf_page_expectations(
            inventory.records,
            {"declared.pdf": 1},
            require_complete_inventory=True,
        )
