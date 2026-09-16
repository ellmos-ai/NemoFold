"""Verify explicit PDF page counts against inventoried, unchanged source bytes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .contracts import SourceRecord
from .document_extract import count_pdf_pages


@dataclass(frozen=True, slots=True)
class PdfPageCheck:
    source_id: str
    display_name: str
    sha256: str
    expected_pages: int
    physical_pages: int

    def as_payload(self) -> dict[str, str | int]:
        return {
            "producer_source_id": self.source_id,
            "display_name": self.display_name,
            "sha256": self.sha256,
            "expected_pages": self.expected_pages,
            "physical_pages": self.physical_pages,
        }


class PdfPageExpectationError(ValueError):
    def __init__(self, code: str, display_name: str) -> None:
        super().__init__(f"{code}:{display_name}")
        self.code = code
        self.display_name = display_name


def verify_pdf_page_expectations(
    sources: tuple[SourceRecord, ...], expectations: dict[str, int]
) -> tuple[PdfPageCheck, ...]:
    """Check every declared source; absence cannot be guessed without a declaration."""
    checks: list[PdfPageCheck] = []
    for display_name, expected_pages in sorted(expectations.items()):
        matched = [source for source in sources if source.display_name == display_name]
        if not matched:
            raise PdfPageExpectationError("expected_pdf_source_missing", display_name)
        if len(matched) != 1:
            raise PdfPageExpectationError("expected_pdf_source_ambiguous", display_name)
        source = matched[0]
        path = Path(source.path)
        if (
            path.suffix.casefold() != ".pdf"
            or path.is_symlink()
            or source.extraction_status in {"unreadable", "excluded_symlink"}
        ):
            raise PdfPageExpectationError("expected_pdf_source_unreadable", display_name)
        try:
            physical_pages = count_pdf_pages(
                path, expected_sha256=source.sha256
            )
        except (OSError, RuntimeError, ValueError):
            raise PdfPageExpectationError(
                "expected_pdf_source_unreadable", display_name
            ) from None
        if physical_pages != expected_pages:
            raise PdfPageExpectationError(
                "expected_pdf_page_gap" if physical_pages < expected_pages
                else "expected_pdf_page_extra",
                display_name,
            )
        checks.append(PdfPageCheck(
            source.source_id, display_name, source.sha256,
            expected_pages, physical_pages,
        ))
    return tuple(checks)
