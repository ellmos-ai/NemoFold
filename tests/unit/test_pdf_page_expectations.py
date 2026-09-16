"""Explicit PDF page expectations must use the physical, hash-bound PDF count."""

from __future__ import annotations

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from nemofold.inventory import scan_paths
from nemofold.pdf_page_expectations import (
    PdfPageExpectationError,
    verify_pdf_page_expectations,
)


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
