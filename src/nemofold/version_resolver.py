from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class VersionCandidate:
    source_id: str
    display_name: str
    issue_date: date | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    version_number: tuple[int, ...] | None = None
    file_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class VersionResolution:
    selected: VersionCandidate
    ordered_source_ids: tuple[str, ...]
    basis: str
    used_file_time_fallback: bool


@dataclass(frozen=True, slots=True)
class VersionComparison:
    added_lines: tuple[str, ...]
    removed_lines: tuple[str, ...]


def _validity_rank(candidate: VersionCandidate, as_of: date) -> int:
    has_validity = candidate.valid_from is not None or candidate.valid_until is not None
    if not has_validity:
        return 1
    starts_in_time = candidate.valid_from is None or candidate.valid_from <= as_of
    ends_in_time = candidate.valid_until is None or as_of <= candidate.valid_until
    return 2 if starts_in_time and ends_in_time else 0


def _rank(candidate: VersionCandidate, as_of: date) -> tuple[object, ...]:
    issue = candidate.issue_date.toordinal() if candidate.issue_date else -1
    version = candidate.version_number or ()
    file_time = candidate.file_time.timestamp() if candidate.file_time else float("-inf")
    return (_validity_rank(candidate, as_of), issue, version, file_time, candidate.source_id)


def resolve_current(
    candidates: Sequence[VersionCandidate],
    *,
    as_of: date,
    fallback_to_file_time: bool = True,
) -> VersionResolution:
    if not candidates:
        raise ValueError("at least one version candidate is required")
    if not fallback_to_file_time and not any(
        candidate.issue_date is not None
        or candidate.valid_from is not None
        or candidate.valid_until is not None
        or candidate.version_number is not None
        for candidate in candidates
    ):
        raise ValueError("version evidence is missing and file-time fallback is disabled")
    ordered = tuple(sorted(candidates, key=lambda item: _rank(item, as_of), reverse=True))
    selected = ordered[0]
    selected_is_explicitly_valid = _validity_rank(selected, as_of) == 2
    if selected_is_explicitly_valid:
        basis = "validity+issue_date" if selected.issue_date else "validity"
    elif selected.issue_date is not None:
        basis = "issue_date"
    elif selected.version_number is not None:
        basis = "version_number"
    else:
        basis = "file_time_fallback"
    return VersionResolution(
        selected=selected,
        ordered_source_ids=tuple(item.source_id for item in ordered),
        basis=basis,
        used_file_time_fallback=basis == "file_time_fallback",
    )


def infer_family_key(display_name: str) -> str:
    stem = Path(display_name).stem.casefold()
    without_dates = re.sub(r"(?<!\d)20\d{2}[-_.]\d{2}[-_.]\d{2}(?!\d)", " ", stem)
    without_versions = re.sub(
        r"(?i)(?:^|[-_.\s])v\d+(?:[-_.]\d+)*(?=$|[-_.\s])",
        " ",
        without_dates,
    )
    normalized = re.sub(r"[-_.\s]+", " ", without_versions).strip()
    return normalized or stem


def compare_versions(old_text: str, new_text: str) -> VersionComparison:
    delta = difflib.ndiff(old_text.splitlines(), new_text.splitlines())
    added: list[str] = []
    removed: list[str] = []
    for line in delta:
        if line.startswith("+ "):
            added.append(line[2:])
        elif line.startswith("- "):
            removed.append(line[2:])
    return VersionComparison(added_lines=tuple(added), removed_lines=tuple(removed))
