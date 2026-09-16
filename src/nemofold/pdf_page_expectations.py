"""Verify explicit PDF page counts against inventoried, unchanged source bytes."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .contracts import SourceRecord
from .document_extract import (
    count_pdf_pages,
    extract_pdf_pages,
    pdf_image_page_numbers,
)


@dataclass(frozen=True, slots=True)
class PdfPageReview:
    page: int
    source_sha256: str
    method: str
    reviewer: str
    reviewed_at: str
    content_complete: bool
    text: str

    def as_parameter_payload(self) -> dict[str, object]:
        return {
            "page": self.page,
            "source_sha256": self.source_sha256,
            "method": self.method,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "content_complete": self.content_complete,
            "text": self.text,
        }

    def as_summary(self) -> dict[str, object]:
        return {
            "page": self.page,
            "method": self.method,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "content_complete": self.content_complete,
            "text_sha256": hashlib.sha256(self.text.encode("utf-8")).hexdigest(),
        }


@dataclass(frozen=True, slots=True)
class PdfPageCheck:
    source_id: str
    display_name: str
    sha256: str
    expected_pages: int
    physical_pages: int
    extractable_text_pages: int
    reviewed_pages: tuple[PdfPageReview, ...] = ()

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "producer_source_id": self.source_id,
            "display_name": self.display_name,
            "sha256": self.sha256,
            "expected_pages": self.expected_pages,
            "physical_pages": self.physical_pages,
            "extractable_text_pages": self.extractable_text_pages,
        }
        if self.reviewed_pages:
            payload["reviewed_pages"] = [
                review.as_summary() for review in self.reviewed_pages
            ]
        return payload


class PdfPageExpectationError(ValueError):
    def __init__(self, code: str, display_name: str, page_number: int | None = None) -> None:
        suffix = f":page={page_number}" if page_number is not None else ""
        super().__init__(f"{code}:{display_name}{suffix}")
        self.code = code
        self.display_name = display_name
        self.page_number = page_number


_REVIEW_FIELDS = frozenset({
    "page",
    "source_sha256",
    "method",
    "reviewer",
    "reviewed_at",
    "content_complete",
    "text",
})


def _parse_page_review_map(
    value: object,
    *,
    label: str,
    source_id_keys: bool,
) -> dict[str, tuple[PdfPageReview, ...]]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 500:
        raise ValueError(f"{label} must be a bounded source map")
    parsed: dict[str, tuple[PdfPageReview, ...]] = {}
    normalized_names: set[str] = set()
    total_text_bytes = 0
    for name, raw_reviews in value.items():
        normalized = name.casefold() if isinstance(name, str) else ""
        valid_name = (
            isinstance(name, str)
            and bool(name)
            and len(name) <= 240
            and normalized not in normalized_names
        )
        if source_id_keys:
            valid_name = valid_name and re.fullmatch(r"src_[a-f0-9]{16}", name) is not None
        else:
            valid_name = (
                valid_name
                and "\\" not in name
                and ":" not in name
                and name.casefold().endswith(".pdf")
                and all(part not in {"", ".", ".."} for part in name.split("/"))
            )
        if not valid_name or not isinstance(raw_reviews, list) or not raw_reviews:
            raise ValueError(f"{label} contains an invalid source or review list")
        if len(raw_reviews) > 10000:
            raise ValueError(f"{label} contains too many page reviews")
        normalized_names.add(normalized)
        reviews: list[PdfPageReview] = []
        page_numbers: set[int] = set()
        for raw in raw_reviews:
            if not isinstance(raw, dict) or set(raw) != _REVIEW_FIELDS:
                raise ValueError(f"{label} contains an invalid review object")
            page = raw["page"]
            source_sha256 = raw["source_sha256"]
            method = raw["method"]
            reviewer = raw["reviewer"]
            reviewed_at = raw["reviewed_at"]
            content_complete = raw["content_complete"]
            text = raw["text"]
            if (
                isinstance(page, bool)
                or not isinstance(page, int)
                or not 1 <= page <= 10000
                or page in page_numbers
                or not isinstance(source_sha256, str)
                or re.fullmatch(r"[a-f0-9]{64}", source_sha256) is None
                or method not in {"manual", "ocr"}
                or not isinstance(reviewer, str)
                or not reviewer.strip()
                or len(reviewer) > 200
                or not isinstance(reviewed_at, str)
                or len(reviewed_at) > 64
                or content_complete is not True
                or not isinstance(text, str)
                or not text.strip()
                or len(text.encode("utf-8")) > 200_000
            ):
                raise ValueError(f"{label} contains an incomplete page review")
            try:
                timestamp = datetime.fromisoformat(reviewed_at)
            except ValueError:
                raise ValueError(f"{label} contains an invalid reviewed_at") from None
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(f"{label} contains an invalid reviewed_at")
            total_text_bytes += len(text.encode("utf-8"))
            if total_text_bytes > 5_000_000:
                raise ValueError(f"{label} reviewed text exceeds the size limit")
            page_numbers.add(page)
            reviews.append(PdfPageReview(
                page=page,
                source_sha256=source_sha256,
                method=method,
                reviewer=reviewer.strip(),
                reviewed_at=reviewed_at,
                content_complete=True,
                text=text.strip(),
            ))
        parsed[name] = tuple(sorted(reviews, key=lambda item: item.page))
    return parsed


def parse_pdf_page_reviews(value: object) -> dict[str, tuple[PdfPageReview, ...]]:
    """Validate explicit page-review attestations keyed by PDF inventory name."""
    return _parse_page_review_map(
        value, label="pdf_page_reviews", source_id_keys=False
    )


def parse_source_page_reviews(value: object) -> dict[str, tuple[PdfPageReview, ...]]:
    """Validate handoff-bound review overlays keyed by consumer source ID."""
    return _parse_page_review_map(
        value, label="source_page_reviews", source_id_keys=True
    )


def verify_pdf_page_expectations(
    sources: tuple[SourceRecord, ...],
    expectations: dict[str, int],
    *,
    require_complete_inventory: bool = False,
    page_reviews: object = None,
) -> tuple[PdfPageCheck, ...]:
    """Check every declared source; absence cannot be guessed without a declaration."""
    reviews_by_name = parse_pdf_page_reviews(page_reviews)
    undeclared_reviews = sorted(set(reviews_by_name) - set(expectations))
    if undeclared_reviews:
        raise PdfPageExpectationError(
            "expected_pdf_page_review_source_undeclared", undeclared_reviews[0]
        )
    if require_complete_inventory:
        undeclared = sorted(
            source.display_name
            for source in sources
            if Path(source.path).suffix.casefold() == ".pdf"
            and source.display_name not in expectations
        )
        if undeclared:
            raise PdfPageExpectationError(
                "expected_pdf_source_undeclared", undeclared[0]
            )
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
        try:
            pages = extract_pdf_pages(path, expected_sha256=source.sha256)
            image_page_numbers = pdf_image_page_numbers(
                path, expected_sha256=source.sha256
            )
        except (OSError, RuntimeError, ValueError):
            raise PdfPageExpectationError(
                "expected_pdf_source_unreadable", display_name
            ) from None
        if len(pages) != physical_pages:
            raise PdfPageExpectationError(
                "expected_pdf_source_unreadable", display_name
            )
        reviews = reviews_by_name.get(display_name, ())
        review_by_page = {review.page: review for review in reviews}
        for review in reviews:
            if review.source_sha256 != source.sha256:
                raise PdfPageExpectationError(
                    "expected_pdf_page_review_source_mismatch",
                    display_name,
                    review.page,
                )
            if review.page > physical_pages:
                raise PdfPageExpectationError(
                    "expected_pdf_page_review_out_of_range", display_name, review.page
                )
        image_pages = set(image_page_numbers)
        missing_text_pages = {
            page_number
            for page_number, text in enumerate(pages, start=1)
            if not text.strip()
        }
        review_required = image_pages | missing_text_pages
        unneeded_reviews = sorted(set(review_by_page) - review_required)
        if unneeded_reviews:
            raise PdfPageExpectationError(
                "expected_pdf_page_review_unneeded",
                display_name,
                unneeded_reviews[0],
            )
        for page_number in sorted(review_required):
            if page_number in review_by_page:
                continue
            raise PdfPageExpectationError(
                (
                    "expected_pdf_page_image_review_required"
                    if page_number in image_pages
                    else "expected_pdf_page_text_missing"
                ),
                display_name,
                page_number,
            )
        effective_pages = list(pages)
        for review in reviews:
            effective_pages[review.page - 1] = review.text
        if any(not text.strip() for text in effective_pages):
            raise PdfPageExpectationError(
                "expected_pdf_page_text_missing", display_name
            )
        checks.append(PdfPageCheck(
            source.source_id, display_name, source.sha256,
            expected_pages, physical_pages, len(effective_pages), reviews,
        ))
    return tuple(checks)


def extract_reviewed_pdf_text(source: SourceRecord, check: PdfPageCheck) -> str:
    """Return the PDF text with only verified incomplete pages replaced."""
    if source.source_id != check.source_id or source.sha256 != check.sha256:
        raise ValueError("reviewed_pdf_source_mismatch")
    pages = list(extract_pdf_pages(source.path, expected_sha256=source.sha256))
    if len(pages) != check.physical_pages:
        raise ValueError("reviewed_pdf_page_count_changed")
    for review in check.reviewed_pages:
        if review.source_sha256 != source.sha256 or review.page > len(pages):
            raise ValueError("reviewed_pdf_page_mismatch")
        pages[review.page - 1] = review.text
    if any(not page.strip() for page in pages):
        raise ValueError("reviewed_pdf_page_text_missing")
    return "\f".join(pages)
