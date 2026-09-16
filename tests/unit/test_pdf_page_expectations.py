"""Explicit PDF page expectations must use the physical, hash-bound PDF count."""

from __future__ import annotations

import pytest
from pypdf import PdfWriter

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
