from __future__ import annotations

from nemofold.contracts import Claim, EvidenceLocator
from nemofold.evidence import compute_coverage, validate_claim


def test_claim_is_verified_only_when_quote_exists_in_known_source() -> None:
    claim = Claim(
        statement="The policy starts in April.",
        evidence=(
            EvidenceLocator(
                source_id="src_policy",
                quote="Coverage begins on 1 April 2026.",
                section="Policy period",
            ),
        ),
    )

    result = validate_claim(
        claim,
        {"src_policy": "Policy period\nCoverage begins on   1 April 2026."},
    )

    assert result.verified is True
    assert result.invalid_locators == ()


def test_unknown_source_and_false_quote_are_not_silently_accepted() -> None:
    claim = Claim(
        statement="Unsupported statement",
        evidence=(
            EvidenceLocator(source_id="missing", quote="Never happened"),
            EvidenceLocator(source_id="src_a", quote="Wrong quote"),
        ),
    )

    result = validate_claim(claim, {"src_a": "Actual source text"})

    assert result.verified is False
    assert set(result.invalid_locators) == {"missing:unknown_source", "src_a:quote_not_found"}


def test_coverage_names_unread_and_uncited_sources() -> None:
    coverage = compute_coverage(
        all_source_ids={"src_a", "src_b", "src_c"},
        read_source_ids={"src_a", "src_b"},
        cited_source_ids={"src_a"},
    )

    assert coverage.total_sources == 3
    assert coverage.read_sources == 2
    assert coverage.cited_sources == 1
    assert coverage.unread_source_ids == ("src_c",)
    assert coverage.uncited_read_source_ids == ("src_b",)
