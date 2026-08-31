from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.fact_distill import distil_facts, struck_markdown
from nemofold.job_io import parse_job_payload

POLICY_A = """Vertragsstand April
Die Deckung beginnt am 1. April 2026.
Der Beitrag betraegt 148 Euro pro Jahr.
"""

POLICY_B = """Kopie der Police
Die  Deckung   beginnt am 1. April 2026.
Die Selbstbeteiligung liegt bei 250 Euro je Schadensfall.
"""

POLICY_C = """Zweitschrift
DIE DECKUNG BEGINNT AM 1. APRIL 2026!
"""


def test_duplicates_are_struck_but_never_disappear() -> None:
    result = distil_facts(
        ("src_a", "src_b"),
        {"src_a": POLICY_A, "src_b": POLICY_B},
        dedupe_scope="normalized",
    )

    statements = [fact.statement for fact in result.facts]
    assert "Die Deckung beginnt am 1. April 2026." in statements
    assert sum("Deckung beginnt" in item for item in statements) == 1

    struck = result.struck
    assert len(struck) == 1
    assert struck[0].duplicate_source_id == "src_b"
    assert struck[0].kept_source_id == "src_a"
    assert struck[0].kept_line == 2
    # Every kept fact still carries its own anchor.
    assert all(fact.source_id and fact.line for fact in result.facts)


def test_normalized_scope_folds_case_and_punctuation_but_exact_does_not() -> None:
    texts = {"src_a": POLICY_A, "src_c": POLICY_C}

    normalized = distil_facts(("src_a", "src_c"), texts, dedupe_scope="normalized")
    assert normalized.struck_count == 1

    exact = distil_facts(("src_a", "src_c"), texts, dedupe_scope="exact")
    assert exact.struck_count == 0
    assert len(exact.facts) == len(normalized.facts) + 1


def test_focus_terms_narrow_the_distillation_without_hiding_the_count() -> None:
    result = distil_facts(
        ("src_a",), {"src_a": POLICY_A}, focus_terms=("Beitrag",)
    )

    assert [fact.statement for fact in result.facts] == [
        "Der Beitrag betraegt 148 Euro pro Jahr."
    ]
    assert result.considered == 1


def test_unknown_dedupe_scope_is_refused() -> None:
    with pytest.raises(ValueError, match="dedupe_scope must be exact or normalized"):
        distil_facts(("src_a",), {"src_a": POLICY_A}, dedupe_scope="fuzzy")


def test_struck_appendix_names_both_sides_of_every_strike() -> None:
    result = distil_facts(
        ("src_a", "src_b"), {"src_a": POLICY_A, "src_b": POLICY_B}
    )
    markdown = struck_markdown(result)

    assert "# Struck duplicates" in markdown
    assert "Deduplication scope: normalized." in markdown
    assert "struck from src_b, line 2" in markdown
    assert "kept in src_a, line 2" in markdown
    assert "Nothing was deleted from a source." in markdown


def test_empty_appendix_says_so_rather_than_staying_blank() -> None:
    result = distil_facts(("src_a",), {"src_a": POLICY_A})
    assert "No duplicate statement was found" in struck_markdown(result)


def test_fact_distill_runs_end_to_end_and_hashes_its_pdf(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "police-a.txt").write_text(POLICY_A, encoding="utf-8")
    (documents / "police-b.txt").write_text(POLICY_B, encoding="utf-8")

    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "fact_distill",
            "input_roots": [str(documents)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "dedupe_scope": "normalized",
                "formats": ["md", "pdf"],
                "title": "Faktenauszug",
            },
        },
        base_dir=tmp_path,
    )

    report = run_job(
        job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="distill_e2e"
    ).report

    assert report.status is RunStatus.EXECUTED
    assert report.metadata["dedupe_scope"] == "normalized"
    assert report.metadata["duplicates_struck"] == 1
    assert report.metadata["facts_kept"] >= 3

    formats = [artifact.format for artifact in report.artifacts]
    assert "struck-duplicates" in formats
    assert formats.count("pdf") == 2  # findings and the struck appendix

    for artifact in report.artifacts:
        written = Path(artifact.path)
        assert written.is_file()
        assert artifact.sha256 == hashlib.sha256(written.read_bytes()).hexdigest()

    appendix = next(
        Path(artifact.path)
        for artifact in report.artifacts
        if artifact.format == "struck-duplicates"
    ).read_text(encoding="utf-8")
    assert "struck from" in appendix and "kept in" in appendix


def test_german_ordinals_do_not_cut_a_fact_in_half() -> None:
    # "1. April" must not be read as a sentence end: the halves would escape
    # deduplication and the quote would stop being usable as evidence.
    result = distil_facts(
        ("src_a",),
        {"src_a": "Die Deckung beginnt am 1. April 2026. Der Rest bleibt offen."},
    )

    statements = [fact.statement for fact in result.facts]
    assert "Die Deckung beginnt am 1. April 2026." in statements
    assert "Der Rest bleibt offen." in statements
    assert len(statements) == 2
