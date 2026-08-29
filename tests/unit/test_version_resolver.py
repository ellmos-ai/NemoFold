from __future__ import annotations

from datetime import UTC, date, datetime

from nemofold.version_resolver import VersionCandidate, compare_versions, resolve_current


def candidate(
    source_id: str,
    *,
    issue_date: date | None = None,
    valid_from: date | None = None,
    valid_until: date | None = None,
    version_number: tuple[int, ...] | None = None,
    file_time: datetime,
) -> VersionCandidate:
    return VersionCandidate(
        source_id=source_id,
        display_name=f"{source_id}.txt",
        issue_date=issue_date,
        valid_from=valid_from,
        valid_until=valid_until,
        version_number=version_number,
        file_time=file_time,
    )


def test_explicit_validity_beats_newer_file_timestamp() -> None:
    current = candidate(
        "src_current",
        issue_date=date(2026, 3, 1),
        valid_from=date(2026, 4, 1),
        valid_until=date(2026, 12, 31),
        file_time=datetime(2026, 3, 1, tzinfo=UTC),
    )
    expired_but_touched_later = candidate(
        "src_old",
        issue_date=date(2025, 3, 1),
        valid_from=date(2025, 4, 1),
        valid_until=date(2025, 12, 31),
        file_time=datetime(2026, 8, 1, tzinfo=UTC),
    )

    result = resolve_current((expired_but_touched_later, current), as_of=date(2026, 8, 30))

    assert result.selected.source_id == "src_current"
    assert result.basis == "validity+issue_date"
    assert result.used_file_time_fallback is False


def test_version_number_precedes_file_time_when_dates_are_missing() -> None:
    version_two = candidate(
        "src_v2",
        version_number=(2, 0),
        file_time=datetime(2026, 1, 1, tzinfo=UTC),
    )
    version_one_touched_later = candidate(
        "src_v1",
        version_number=(1, 0),
        file_time=datetime(2026, 8, 1, tzinfo=UTC),
    )

    result = resolve_current((version_one_touched_later, version_two), as_of=date(2026, 8, 30))

    assert result.selected.source_id == "src_v2"
    assert result.basis == "version_number"
    assert result.used_file_time_fallback is False


def test_file_time_is_named_when_it_is_the_only_available_fallback() -> None:
    older = candidate(
        "src_older",
        file_time=datetime(2026, 1, 1, tzinfo=UTC),
    )
    newer = candidate(
        "src_newer",
        file_time=datetime(2026, 2, 1, tzinfo=UTC),
    )

    result = resolve_current((older, newer), as_of=date(2026, 8, 30))

    assert result.selected.source_id == "src_newer"
    assert result.basis == "file_time_fallback"
    assert result.used_file_time_fallback is True


def test_version_comparison_reports_added_and_removed_lines() -> None:
    comparison = compare_versions(
        "Coverage: basic\nDeductible: 500",
        "Coverage: plus\nDeductible: 500",
    )

    assert comparison.added_lines == ("Coverage: plus",)
    assert comparison.removed_lines == ("Coverage: basic",)
