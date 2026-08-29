from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from .contracts import Claim, ClaimValidation, Coverage


def _normalize_quote(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def validate_claim(claim: Claim, source_texts: Mapping[str, str]) -> ClaimValidation:
    invalid: list[str] = []
    valid = 0

    for locator in claim.evidence:
        source_text = source_texts.get(locator.source_id)
        if source_text is None:
            invalid.append(f"{locator.source_id}:unknown_source")
            continue
        quote = _normalize_quote(locator.quote)
        if not quote or quote not in _normalize_quote(source_text):
            invalid.append(f"{locator.source_id}:quote_not_found")
            continue
        valid += 1

    return ClaimValidation(
        verified=bool(claim.evidence) and not invalid,
        valid_locator_count=valid,
        invalid_locators=tuple(invalid),
    )


def compute_coverage(
    *,
    all_source_ids: Iterable[str],
    read_source_ids: Iterable[str],
    cited_source_ids: Iterable[str],
) -> Coverage:
    all_ids = set(all_source_ids)
    read_ids = set(read_source_ids) & all_ids
    cited_ids = set(cited_source_ids) & read_ids
    return Coverage(
        total_sources=len(all_ids),
        read_sources=len(read_ids),
        cited_sources=len(cited_ids),
        unread_source_ids=tuple(sorted(all_ids - read_ids)),
        uncited_read_source_ids=tuple(sorted(read_ids - cited_ids)),
    )
