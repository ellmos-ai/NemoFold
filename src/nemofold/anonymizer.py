from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from .document_index import SearchHit
from .evidence_analyst import ContextReceipt


@dataclass(frozen=True, slots=True)
class PseudonymizationResult:
    text: str
    replacement_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class PseudonymizedReceipts:
    receipts: tuple[ContextReceipt, ...]
    replacement_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class PseudonymizedPackageContent:
    questions: tuple[str, ...]
    receipts: tuple[ContextReceipt, ...]
    replacement_counts: dict[str, int]


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "SECRET",
        re.compile(
            r"(?i)(?:AKIA[0-9A-Z]{16}|(?:sk|api)[-_][A-Za-z0-9_-]{16,}|"
            r"bearer\s+[A-Za-z0-9._~+/-]{12,}=*)"
        ),
    ),
    ("EMAIL", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")),
    ("IBAN", re.compile(r"(?i)\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b")),
    (
        "PATH",
        re.compile(
            r"(?i)(?:\b[A-Z]:\\[^\s,;]+|/(?:home|users|root|private|mnt)/[^\s,;]+)"
        ),
    ),
    (
        "PHONE",
        re.compile(r"(?<!\w)(?:\+\d{1,3}[ .()/\-]*)?(?:\d[ .()/\-]*){7,15}(?!\w)"),
    ),
)

_DATE_CANDIDATE = re.compile(
    r"(?:(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4}|\d{2})"
    r"|(?P<iso_year>\d{4})-(?P<iso_month>\d{2})-(?P<iso_day>\d{2}))"
    r"(?:[ ](?P<hour>\d{1,2}))?"
)


def _is_date(match: re.Match[str]) -> bool:
    """A PHONE candidate that is exactly one calendar date stays readable.

    A date has eight digits and used to be masked as a phone number, which left
    an outbound timeline without a single date. The PHONE pattern itself is
    unchanged; only a candidate that is nothing but a valid date between 1900
    and 2100, at most followed by the hour of a time ("13.03.2026 17" before
    ":00") or by sentence punctuation, is exempt. Anything else in the same
    digit run (a following number, a longer identifier) keeps the whole run
    masked.
    """
    candidate = match.group(0).rstrip(" .")
    found = _DATE_CANDIDATE.fullmatch(candidate)
    if found is None:
        return False
    if found["hour"] is not None and (
        match.string[match.end() : match.end() + 1] != ":" or int(found["hour"]) > 23
    ):
        return False
    if found["iso_year"] is not None:
        year, month, day = (int(found[key]) for key in ("iso_year", "iso_month", "iso_day"))
    else:
        year, month, day = (int(found[key]) for key in ("year", "month", "day"))
        if len(found["year"]) == 2:
            year += 2000
    if not 1900 <= year <= 2100:
        return False
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


_EXEMPT: dict[str, Callable[[re.Match[str]], bool]] = {"PHONE": _is_date}


def _sensitive_matches(category: str, pattern: re.Pattern[str], text: str) -> bool:
    exempt = _EXEMPT.get(category)
    return any(exempt is None or not exempt(match) for match in pattern.finditer(text))


def detect_sensitive_categories(text: str) -> tuple[str, ...]:
    """Return deterministic categories still visible in an outbound text field."""
    return tuple(
        category for category, pattern in PATTERNS if _sensitive_matches(category, pattern, text)
    )


class Pseudonymizer:
    """Stateful local mapper that keeps package-wide pseudonyms consistent."""

    def __init__(self, *, sensitive_terms: Sequence[str] = ()) -> None:
        terms = tuple(sorted({item for item in sensitive_terms if item}, key=len, reverse=True))
        self._term_pattern = (
            re.compile("|".join(re.escape(item) for item in terms), re.IGNORECASE)
            if terms
            else None
        )
        self._maps: dict[str, dict[str, str]] = {}

    def _replace(self, text: str, category: str, pattern: re.Pattern[str]) -> str:
        replacements = self._maps.setdefault(category, {})
        exempt = _EXEMPT.get(category)

        def replace_match(match: re.Match[str]) -> str:
            if exempt is not None and exempt(match):
                return match.group(0)
            key = match.group(0).casefold()
            if key not in replacements:
                replacements[key] = f"<{category}_{len(replacements) + 1:03d}>"
            return replacements[key]

        return pattern.sub(replace_match, text)

    def pseudonymize(self, text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        cleaned = text
        if self._term_pattern is not None:
            cleaned = self._replace(cleaned, "TERM", self._term_pattern)
        for category, pattern in PATTERNS:
            cleaned = self._replace(cleaned, category, pattern)
        return cleaned

    @property
    def replacement_counts(self) -> dict[str, int]:
        return {
            category: len(replacements)
            for category, replacements in sorted(self._maps.items())
            if replacements
        }


def pseudonymize_text(
    text: str,
    *,
    sensitive_terms: Sequence[str] = (),
) -> PseudonymizationResult:
    pseudonymizer = Pseudonymizer(sensitive_terms=sensitive_terms)
    cleaned = pseudonymizer.pseudonymize(text)
    return PseudonymizationResult(
        text=cleaned,
        replacement_counts=pseudonymizer.replacement_counts,
    )


def pseudonymize_context_receipts(
    receipts: Sequence[ContextReceipt],
    *,
    sensitive_terms: Sequence[str] = (),
) -> PseudonymizedReceipts:
    content = pseudonymize_questions_and_receipts(
        tuple(receipt.question for receipt in receipts),
        receipts,
        sensitive_terms=sensitive_terms,
    )
    return PseudonymizedReceipts(
        receipts=content.receipts,
        replacement_counts=content.replacement_counts,
    )


def pseudonymize_questions_and_receipts(
    questions: Sequence[str],
    receipts: Sequence[ContextReceipt],
    *,
    sensitive_terms: Sequence[str] = (),
) -> PseudonymizedPackageContent:
    pseudonymizer = Pseudonymizer(sensitive_terms=sensitive_terms)
    sanitized_questions = tuple(pseudonymizer.pseudonymize(item) for item in questions)
    sanitized: list[ContextReceipt] = []
    for receipt in receipts:
        hits: list[SearchHit] = []
        for hit in receipt.hits:
            hits.append(
                SearchHit(
                    chunk_id=hit.chunk_id,
                    source_id=hit.source_id,
                    text=pseudonymizer.pseudonymize(hit.text),
                    rank=hit.rank,
                    char_start=hit.char_start,
                    char_end=hit.char_end,
                    line_start=hit.line_start,
                    line_end=hit.line_end,
                    page_start=hit.page_start,
                    page_end=hit.page_end,
                )
            )
        sanitized.append(
            ContextReceipt(
                question=pseudonymizer.pseudonymize(receipt.question),
                hits=tuple(hits),
            )
        )
    return PseudonymizedPackageContent(
        questions=sanitized_questions,
        receipts=tuple(sanitized),
        replacement_counts=pseudonymizer.replacement_counts,
    )
