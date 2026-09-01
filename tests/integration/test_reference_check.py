from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.job_io import parse_job_payload
from nemofold.reference import (
    REFERENCE_GRIDS,
    grid_named,
    reference_payload,
    validate_against_reference,
    validate_items,
)

BESCHEID = """Absender: Amt für Beispiele
Datum: 12.03.2026
Aktenzeichen: BSP-2026-0042
Empfänger: Tobias Lenz

Ihr Antrag wird bewilligt.

Begründung: Die Voraussetzungen liegen nach den eingereichten Unterlagen vor.
"""


def _job(tmp_path: Path, documents: Path, run_id: str, **parameters):
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "reference_check",
            "input_roots": [str(documents)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": parameters,
        },
        base_dir=tmp_path,
    )
    return run_job(job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id=run_id)


@pytest.fixture
def bescheid(tmp_path: Path) -> Path:
    documents = tmp_path / "post"
    documents.mkdir()
    (documents / "bescheid.md").write_text(BESCHEID, encoding="utf-8")
    return documents


# --------------------------------------------------------------------------- #
# Present means quoted
# --------------------------------------------------------------------------- #


def test_an_answered_item_carries_the_line_that_answered_it() -> None:
    report = validate_against_reference(
        ("bescheid",), {"bescheid": BESCHEID}, grid_named("bescheid_formal"),
        grid="bescheid_formal",
    )

    found = {item.item.key: item for item in report.findings}
    assert found["aktenzeichen"].present is True
    # A checkmark without a quote is an opinion.
    assert "BSP-2026-0042" in found["aktenzeichen"].quote
    assert found["aktenzeichen"].anchor.source_id == "bescheid"
    assert found["aktenzeichen"].anchor.line == 3


def test_a_labelled_line_is_preferred_over_a_loose_mention() -> None:
    text = "Hier geht es um das Aktenzeichen im Allgemeinen.\nAktenzeichen: XY-1\n"

    report = validate_against_reference(
        ("doc",), {"doc": text}, validate_items([{"key": "az", "label": "Aktenzeichen"}])
    )

    # Both mention it; only one is the document answering the item.
    assert report.findings[0].quote.startswith("Aktenzeichen: XY-1")


def test_a_missing_item_is_listed_with_what_was_looked_for(bescheid) -> None:
    report = validate_against_reference(
        ("bescheid",), {"bescheid": BESCHEID}, grid_named("bescheid_formal"),
        grid="bescheid_formal",
    )

    missing = {item.item.key for item in report.missing}
    # The letter carries no appeal instruction and no signature.
    assert "rechtsbehelf" in missing
    assert "unterschrift" in missing
    payload = reference_payload(report)
    entry = next(item for item in payload["missing"] if item["key"] == "rechtsbehelf")
    assert "Widerspruch" in entry["looked_for"]


# --------------------------------------------------------------------------- #
# It compares, it does not judge
# --------------------------------------------------------------------------- #


def test_the_report_refuses_to_call_a_document_correct(bescheid, tmp_path) -> None:
    result = _job(tmp_path, bescheid, "check", reference_grid="bescheid_formal",
                  formats=["md"])

    assert result.report.status is RunStatus.EXECUTED
    payload = json.loads(
        (tmp_path / "out" / "check.reference-check.json").read_text(encoding="utf-8")
    )
    note = payload["no_judgement_note"]
    assert "does not say the document is correct, valid, sufficient or lawful" in note
    assert "is not advice" in note
    assert "somebody qualified" in note
    # "complete" is about the checklist, never about the document.
    assert payload["complete"] is False
    assert payload["present_count"] >= 5


@pytest.mark.parametrize("grid", sorted(REFERENCE_GRIDS))
def test_every_shipped_grid_is_a_usable_checklist(grid) -> None:
    items = grid_named(grid)

    assert items
    assert all(item.key and item.label and item.terms for item in items)


def test_an_unknown_grid_names_the_ones_that_exist() -> None:
    with pytest.raises(ValueError, match="Available: bescheid_formal"):
        grid_named("gibt_es_nicht")


def test_a_check_without_anything_to_check_against_is_refused(tmp_path, bescheid) -> None:
    result = _job(tmp_path, bescheid, "empty", formats=["md"])

    assert result.report.status is RunStatus.FAILED


# --------------------------------------------------------------------------- #
# As a review step in a chain
# --------------------------------------------------------------------------- #


def test_a_required_review_stops_the_chain_and_asks(tmp_path, bescheid) -> None:
    result = _job(
        tmp_path,
        bescheid,
        "review",
        reference_grid="bescheid_formal",
        require_complete=True,
        formats=["md"],
    )

    assert result.report.status is RunStatus.BLOCKED
    assert result.report.metadata["needs_user_input"] is True
    assert any(item == "reference_missing:rechtsbehelf" for item in result.report.errors)
    asked = json.loads(
        (tmp_path / "out" / "review.needs-user-input.json").read_text(encoding="utf-8")
    )
    question = next(
        item for item in asked["questions"] if item["field"] == "reference.rechtsbehelf"
    )
    assert "Rechtsbehelfsbelehrung" in question["prompt"]
    assert "Pflichtpunkt" in question["why"]


def test_without_require_complete_the_step_reports_and_continues(tmp_path, bescheid) -> None:
    result = _job(
        tmp_path, bescheid, "soft", reference_grid="bescheid_formal", formats=["md"]
    )

    # A review that blocks by default would make it unusable as a quality step
    # somebody inserts to look, rather than to gate.
    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["complete"] is False
    assert "rechtsbehelf" in result.report.metadata["missing_keys"]


def test_the_design_review_grid_works_on_a_voyage_description(tmp_path) -> None:
    documents = tmp_path / "plan"
    documents.mkdir()
    (documents / "voyage.md").write_text(
        "Zweck: Alle Personen der Akte auflisten.\n"
        "Quelle: examples/synthetic-case\n"
        "Ergebnis: Register als PDF.\n",
        encoding="utf-8",
    )

    result = _job(
        tmp_path, documents, "design", reference_grid="voyage_design_review", formats=["md"]
    )

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["present_count"] >= 3
    # The one thing the plan does not say is what it will not do.
    assert "grenzen" in result.report.metadata["missing_keys"]
