from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.completeness import (
    Question,
    check_completeness,
    completeness_payload,
    needs_input_payload,
    validate_question,
)
from nemofold.contracts import RunStatus
from nemofold.job_io import parse_job_payload

# --------------------------------------------------------------------------- #
# Asking back, in a shape a form can render
# --------------------------------------------------------------------------- #


def test_a_question_names_the_field_it_is_about() -> None:
    question = validate_question(
        {
            "field": "to",
            "prompt": "An welche Adresse soll der Entwurf gehen?",
            "why": "Die Quellen nennen keinen Empfänger.",
            "kind": "address",
        }
    )

    payload = needs_input_payload((question,), workflow="controlled_email")

    assert payload["question_count"] == 1
    assert payload["questions"][0]["field"] == "to"
    assert payload["questions"][0]["kind"] == "address"
    # The outcome says why it stopped rather than only that it did.
    assert "would otherwise have guessed" in payload["outcome_note"]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"prompt": "x"}, "needs the field"),
        ({"field": "to"}, "needs the field"),
        ({"field": "to", "prompt": "x", "kind": "telepathy"}, "kind must be one of"),
        ({"field": "to", "prompt": "x", "kind": "choice"}, "needs its choices"),
        ({"field": "to", "prompt": "x", "extra": 1}, "holds only field"),
    ],
)
def test_an_unusable_question_is_refused(value, message) -> None:
    with pytest.raises(ValueError, match=message):
        validate_question(value)


def test_a_run_may_not_bury_a_person_in_questions() -> None:
    questions = tuple(
        Question(field=f"f{index}", prompt="?", why="") for index in range(21)
    )

    with pytest.raises(ValueError, match="more than 20 questions"):
        needs_input_payload(questions, workflow="x")


# --------------------------------------------------------------------------- #
# Completeness reports both ways
# --------------------------------------------------------------------------- #


def test_a_complete_bundle_says_what_it_verified() -> None:
    report = check_completeness(
        total_sources=3,
        read_sources=3,
        unread_source_ids=(),
        required_formats=("md", "pdf"),
        available_formats=("md", "pdf", "txt"),
        required_parts={"findings": 4},
    )

    assert report.complete is True
    # A passing check that says nothing is as useless as a failing one that
    # says only "incomplete".
    details = {item.check: item.detail for item in report.findings}
    assert details["sources_read"] == "3 of 3 source(s) were read"
    assert details["formats_available"] == "every required format can be produced"
    assert details["required_parts_filled"] == "every required part carries content"


def test_an_unread_source_names_itself() -> None:
    report = check_completeness(
        total_sources=3,
        read_sources=2,
        unread_source_ids=("scan-3",),
        required_formats=(),
        available_formats=("md",),
        required_parts={},
    )

    assert report.complete is False
    assert "scan-3" in report.failed[0].detail


def test_a_format_that_cannot_be_produced_is_named() -> None:
    report = check_completeness(
        total_sources=1,
        read_sources=1,
        unread_source_ids=(),
        required_formats=("md", "epub"),
        available_formats=("md",),
        required_parts={},
    )

    assert report.complete is False
    assert "cannot produce: epub" in report.failed[0].detail


def test_an_empty_required_part_is_a_failure_not_a_pass() -> None:
    report = check_completeness(
        total_sources=1,
        read_sources=1,
        unread_source_ids=(),
        required_formats=(),
        available_formats=("md",),
        required_parts={"findings": 0, "appendix": 2},
    )

    assert report.complete is False
    assert "empty required part(s): findings" in report.failed[0].detail
    assert "concludes nothing about content" in completeness_payload(report)["scope_note"]


# --------------------------------------------------------------------------- #
# As a step in a chain
# --------------------------------------------------------------------------- #


def _bundle(tmp_path: Path) -> Path:
    documents = tmp_path / "buendel"
    documents.mkdir()
    (documents / "a.txt").write_text("Erster Teil", encoding="utf-8")
    (documents / "b.txt").write_text("Zweiter Teil", encoding="utf-8")
    return documents


def _check(tmp_path: Path, documents: Path, run_id: str, **parameters):
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "bundle_completeness_check",
            "input_roots": [str(documents)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": parameters,
        },
        base_dir=tmp_path,
    )
    return run_job(job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id=run_id)


def test_a_complete_bundle_passes_the_step(tmp_path) -> None:
    result = _check(tmp_path, _bundle(tmp_path), "ok", required_formats=["md", "pdf"])

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["complete"] is True
    payload = json.loads((tmp_path / "out" / "ok.completeness.json").read_text("utf-8"))
    assert payload["complete"] is True
    assert len(payload["checks"]) == 3


def test_an_incomplete_bundle_stops_the_chain_there(tmp_path) -> None:
    result = _check(
        tmp_path, _bundle(tmp_path), "bad", required_formats=["epub"]
    )

    # A chain has to stop here, or the next step inherits the gap silently.
    assert result.report.status is RunStatus.BLOCKED
    assert any("formats_available" in error for error in result.report.errors)
    assert result.report.metadata["failed_checks"] == ["formats_available"]


def test_printing_asks_which_document_rather_than_taking_the_first(tmp_path) -> None:
    documents = tmp_path / "post"
    documents.mkdir()
    for name in ("a.md", "b.md", "c.md"):
        (documents / name).write_text(f"# {name}", encoding="utf-8")

    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "print_action",
            "input_roots": [str(documents)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {"formats": ["md"]},
        },
        base_dir=tmp_path,
    )
    result = run_job(job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="which")

    # Printing the first of several is a choice this run has no basis for, and
    # the wrong document is not something a receipt would catch.
    assert result.report.status is RunStatus.BLOCKED
    assert result.report.metadata["needs_user_input"] is True
    assert result.report.metadata["candidate_count"] == 3
    asked = json.loads(
        (tmp_path / "out" / "which.needs-user-input.json").read_text(encoding="utf-8")
    )
    question = asked["questions"][0]
    assert question["field"] == "source_id"
    assert question["kind"] == "choice"
    assert len(question["choices"]) == 3


def test_printing_one_named_document_does_not_ask(tmp_path) -> None:
    documents = tmp_path / "post"
    documents.mkdir()
    (documents / "a.md").write_text("# a", encoding="utf-8")
    (documents / "b.md").write_text("# b", encoding="utf-8")

    listing = run_job(
        parse_job_payload(
            {
                "schema": "nemofold.job.v1",
                "workflow": "print_action",
                "input_roots": [str(documents)],
                "output_dir": str(tmp_path / "out"),
                "privacy_mode": "local_only",
                "action_mode": "dry_run",
                "parameters": {},
            },
            base_dir=tmp_path,
        ),
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="ask",
    )
    chosen = json.loads(
        (tmp_path / "out" / "ask.needs-user-input.json").read_text(encoding="utf-8")
    )["questions"][0]["choices"][0]
    assert listing.report.status is RunStatus.BLOCKED

    result = run_job(
        parse_job_payload(
            {
                "schema": "nemofold.job.v1",
                "workflow": "print_action",
                "input_roots": [str(documents)],
                "output_dir": str(tmp_path / "out"),
                "privacy_mode": "local_only",
                "action_mode": "dry_run",
                "parameters": {"source_id": chosen},
            },
            base_dir=tmp_path,
        ),
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="named",
    )

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["printed"] is False
