from __future__ import annotations

import zipfile

import pytest

from nemofold.contracts import Claim, Coverage, EvidenceLocator
from nemofold.report_studio import ReportDocument, render_report_formats


def document() -> ReportDocument:
    return ReportDocument(
        title="Synthetic policy report",
        claims=(
            Claim(
                statement="Coverage begins in April.",
                evidence=(
                    EvidenceLocator(
                        source_id="src_policy",
                        quote="Coverage begins on 1 April 2026.",
                        page=1,
                    ),
                ),
            ),
        ),
        coverage=Coverage(
            total_sources=2,
            read_sources=1,
            cited_sources=1,
            unread_source_ids=("src_old",),
        ),
    )


def test_all_formats_preserve_source_ids_and_are_openable_packages(tmp_path) -> None:
    records = render_report_formats(document(), tmp_path, basename="policy_report")
    by_format = {record.format: record for record in records}

    assert set(by_format) == {"markdown", "text", "pdf", "docx", "odt"}
    assert (tmp_path / "policy_report.pdf").read_bytes().startswith(b"%PDF-1.4")
    assert "src_policy" in (tmp_path / "policy_report.md").read_text(encoding="utf-8")
    assert "src_old" in (tmp_path / "policy_report.txt").read_text(encoding="utf-8")

    with zipfile.ZipFile(tmp_path / "policy_report.docx") as archive:
        assert "word/document.xml" in archive.namelist()
        assert b"src_policy" in archive.read("word/document.xml")
    with zipfile.ZipFile(tmp_path / "policy_report.odt") as archive:
        assert archive.namelist()[0] == "mimetype"
        assert archive.read("mimetype") == b"application/vnd.oasis.opendocument.text"
        assert b"src_old" in archive.read("content.xml")


def test_unsupported_format_is_rejected_before_any_output_is_written(tmp_path) -> None:
    with pytest.raises(ValueError):
        render_report_formats(document(), tmp_path, basename="report", formats=("md", "exe"))

    assert list(tmp_path.iterdir()) == []


def test_pdf_does_not_silently_drop_sources_after_first_page(tmp_path) -> None:
    claims = tuple(
        Claim(
            statement=f"Claim {index} with enough text to occupy a separate report line.",
            evidence=(
                EvidenceLocator(source_id=f"src_{index:03d}", quote=f"Evidence {index}"),
            ),
        )
        for index in range(90)
    )
    large = ReportDocument(
        title="Large report",
        claims=claims,
        coverage=Coverage(total_sources=90, read_sources=90, cited_sources=90),
    )

    render_report_formats(large, tmp_path, basename="large", formats=("pdf",))
    pdf = (tmp_path / "large.pdf").read_bytes()

    assert b"src_089" in pdf
    assert pdf.count(b"/Type /Page ") >= 2
