from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.interrater import (
    Coding,
    cohens_kappa,
    interrater_diff,
    interrater_payload,
    validate_codes,
)
from nemofold.job_io import parse_job_payload

SURVEY = Path(__file__).resolve().parents[2] / "examples" / "synthetic-survey"
SCHEME = {
    "zufrieden": ["zufrieden"],
    "unzufrieden": ["unzufrieden"],
    "keine_angabe": ["keine angabe"],
}


def _coding(rater: str, codes: dict[str, str]) -> Coding:
    return Coding(rater=rater, codes=codes, anchors={})


def _race(tmp_path: Path, run_id: str, **parameters):
    payload = {
        "coding_scheme": SCHEME,
        "scan_labels": ["Antwort", "Nachtrag"],
        "formats": ["md"],
    }
    payload.update(parameters)
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "rater_race",
            "input_roots": [str(SURVEY)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": payload,
        },
        base_dir=tmp_path,
    )
    return run_job(
        job, ExecutionConfig(allowed_roots=(str(tmp_path), str(SURVEY))), run_id=run_id
    )


# --------------------------------------------------------------------------- #
# Two numbers, never one
# --------------------------------------------------------------------------- #


def test_perfect_agreement_reports_both_numbers() -> None:
    report = interrater_diff(
        _coding("a", {"1": "ja", "2": "nein"}), _coding("b", {"1": "ja", "2": "nein"})
    )

    assert report.agreement.percent == 100.0
    assert report.agreement.kappa == 1.0
    assert report.agreement.kappa_note == ""


def test_a_dominant_code_shows_why_percent_alone_misleads() -> None:
    # Nine of ten items are "other" and both raters say so; they part on the one
    # interesting item. Ninety per cent looks excellent.
    codes_a = {str(index): "other" for index in range(9)}
    codes_a["9"] = "besonders"
    codes_b = {str(index): "other" for index in range(10)}

    report = interrater_diff(_coding("a", codes_a), _coding("b", codes_b))

    assert report.agreement.percent == 90.0
    # Kappa knows that agreeing on "other" is what chance would do anyway.
    assert report.agreement.kappa is not None
    assert report.agreement.kappa < 0.5


def test_kappa_says_it_is_undefined_rather_than_printing_a_number() -> None:
    same = {"1": "ja", "2": "ja"}
    report = interrater_diff(_coding("a", same), _coding("b", same))

    kappa, note = cohens_kappa(report.cells)

    assert kappa is None
    assert "single category" in note
    # 0.0 or 1.0 here would read as a finding about the raters rather than about
    # the arithmetic.
    payload = interrater_payload(report)
    assert payload["cohens_kappa"] is None
    assert payload["kappa_note"]


def test_an_item_only_one_rater_saw_is_reported_not_counted() -> None:
    report = interrater_diff(
        _coding("a", {"1": "ja", "2": "ja"}), _coding("b", {"1": "ja"})
    )

    assert report.agreement.items == 1
    assert report.only_in_a == ("2",)
    assert report.only_in_b == ()


def test_the_disagreements_are_the_output_worth_reading() -> None:
    payload = interrater_payload(
        interrater_diff(
            _coding("a", {"1": "ja", "2": "nein"}), _coding("b", {"1": "ja", "2": "ja"})
        )
    )

    assert payload["disagreements"] == [
        {"item_id": "2", "display_name": "2", "code_a": "nein", "code_b": "ja"}
    ]
    assert "where the coding scheme is ambiguous, not where a rater was wrong" in (
        payload["reading_note"]
    )


def test_reading_the_whole_form_codes_the_question_not_the_answer(tmp_path) -> None:
    # Every stem says "Wie zufrieden sind Sie?", so without declared fields the
    # first-match reader codes the question on every single form - identically,
    # which looks exactly like agreement.
    _race(tmp_path, "stem", scan_labels=[])

    payload = json.loads(
        (tmp_path / "out" / "stem.interrater.json").read_text(encoding="utf-8")
    )
    assert payload["disagreed"] > 3


@pytest.mark.parametrize(
    ("scheme", "message"),
    [
        ({}, "at least one code"),
        ({"a": []}, "no term to look for"),
        ({"a": "nicht liste"}, "must be a list"),
    ],
)
def test_an_unusable_coding_scheme_is_refused(scheme, message) -> None:
    with pytest.raises(ValueError, match=message):
        validate_codes(scheme)


# --------------------------------------------------------------------------- #
# The race over the synthetic questionnaires
# --------------------------------------------------------------------------- #


def test_two_readings_of_the_same_forms_part_where_they_are_ambiguous(tmp_path) -> None:
    result = _race(tmp_path, "race")

    assert result.report.status is RunStatus.EXECUTED
    payload = json.loads(
        (tmp_path / "out" / "race.interrater.json").read_text(encoding="utf-8")
    )
    # Three of the eight forms carry one sentiment early and another late, which
    # is exactly where reading for the first and for the last indication differ.
    assert payload["item_count"] == 8
    assert payload["disagreed"] == 3
    assert payload["percent_agreement"] == 62.5
    assert payload["cohens_kappa"] is not None
    # The id stays the opaque source id; the display name is what a person reads.
    disputed = {item["display_name"] for item in payload["disagreements"]}
    assert disputed == {"fb-03.md", "fb-05.md", "fb-07.md"}
    assert all(item["item_id"].startswith("src_") for item in payload["disagreements"])


def test_the_race_exports_the_cell_diff_as_a_workbook(tmp_path) -> None:
    openpyxl = pytest.importorskip("openpyxl")

    result = _race(tmp_path, "book", rater_a="Modell A", rater_b="Modell B")

    assert result.report.status is RunStatus.EXECUTED
    book = next(
        Path(item.path)
        for item in result.report.artifacts
        if item.format == "table-workbook"
    )
    sheet = openpyxl.load_workbook(io.BytesIO(book.read_bytes())).active
    rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    assert rows[0] == ["Dokument", "Modell A", "Modell B", "einig"]
    assert len(rows) == 9
    # Readable file names, not hashed ids.
    assert {row[0] for row in rows[1:]} == {f"fb-0{index}.md" for index in range(1, 9)}
    assert any(row[3] == "nein" for row in rows[1:])


def test_full_agreement_still_produces_a_report(tmp_path) -> None:
    # A race that finds nothing is a result, not a missing file.
    result = _race(tmp_path, "same", coding_scheme={"alles": ["Antwort"]}, scan_labels=[])

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["disagreed"] == 0
    findings = (tmp_path / "out" / "same_interrater.md").read_text(encoding="utf-8")
    assert "Das ist das Ergebnis, kein fehlender Bericht." in findings
