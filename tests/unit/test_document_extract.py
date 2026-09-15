from __future__ import annotations

import hashlib
import zipfile

import pytest

from nemofold.contracts import Coverage
from nemofold.document_extract import (
    SourceHashMismatch,
    UnsupportedDocumentError,
    extract_document_text,
)
from nemofold.report_studio import ReportDocument, render_report_formats


def test_docx_and_odt_are_extracted_locally_with_standard_library(tmp_path) -> None:
    docx = tmp_path / "case.docx"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:body><w:p><w:r><w:t>First paragraph.</w:t></w:r></w:p>
            <w:p><w:r><w:t>Second paragraph.</w:t></w:r></w:p></w:body></w:document>""",
        )
    odt = tmp_path / "case.odt"
    with zipfile.ZipFile(odt, "w") as archive:
        archive.writestr(
            "content.xml",
            """<office:document-content
            xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
            xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
            <office:body><office:text><text:h>Heading</text:h>
            <text:p>ODT paragraph.</text:p></office:text></office:body>
            </office:document-content>""",
        )

    assert extract_document_text(docx) == "First paragraph.\nSecond paragraph."
    assert extract_document_text(odt) == "Heading\nODT paragraph."


def test_html_extractor_keeps_visible_text_and_unknown_types_fail_closed(tmp_path) -> None:
    html = tmp_path / "case.html"
    html.write_text("<h1>Case</h1><p>Visible fact.</p>", encoding="utf-8")
    unknown = tmp_path / "case.bin"
    unknown.write_bytes(b"binary")

    assert extract_document_text(html) == "Case\nVisible fact."
    with pytest.raises(UnsupportedDocumentError):
        extract_document_text(unknown)


def test_pdf_report_round_trips_through_local_text_extractor(tmp_path) -> None:
    records = render_report_formats(
        ReportDocument(
            title="Local PDF evidence",
            claims=(),
            coverage=Coverage(total_sources=0, read_sources=0, cited_sources=0),
        ),
        tmp_path,
        formats=("pdf",),
    )

    extracted = extract_document_text(records[0].path)

    assert "Local PDF evidence" in extracted
    assert "Coverage" in extracted


def test_extraction_rejects_bytes_different_from_the_inventory_hash(tmp_path) -> None:
    source = tmp_path / "report.txt"
    source.write_text("Befund: Schilddrüse unauffällig.\n", encoding="utf-8")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    assert "unauffällig" in extract_document_text(source, expected_sha256=expected)

    source.write_text("Befund: Schilddrüse verändert.\n", encoding="utf-8")
    with pytest.raises(SourceHashMismatch, match="source_hash_mismatch"):
        extract_document_text(source, expected_sha256=expected)
