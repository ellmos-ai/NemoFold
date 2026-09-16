from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.contracts import ActionMode, PrivacyMode
from nemofold.job_io import (
    JobFileError,
    job_snapshot_payload,
    load_job_file,
    load_job_snapshot,
)


def write_job(tmp_path, **overrides):
    payload = {
        "schema": "nemofold.job.v1",
        "workflow": "evidence_analyst",
        "input_roots": ["documents"],
        "target_roots": ["archive"],
        "output_dir": "output",
        "questions": ["What is supported?"],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {"max_chunks": 4},
    }
    payload.update(overrides)
    path = tmp_path / "job.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_job_file_resolves_local_paths_and_preserves_typed_controls(tmp_path) -> None:
    path = write_job(tmp_path)

    loaded = load_job_file(path)

    assert loaded.job.workflow == "evidence_analyst"
    assert loaded.job.input_roots == (str((tmp_path / "documents").resolve()),)
    assert loaded.job.target_roots == (str((tmp_path / "archive").resolve()),)
    assert loaded.job.output_dir == str((tmp_path / "output").resolve())
    assert loaded.job.privacy_mode is PrivacyMode.LOCAL_ONLY
    assert loaded.job.action_mode is ActionMode.DRY_RUN
    assert loaded.job.parameters == {"max_chunks": 4}
    assert loaded.source_path == path.resolve()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"schema": "unknown"}, "schema"),
        ({"workflow": "mail_sender"}, "workflow"),
        ({"questions": []}, "questions"),
        ({"surprise": True}, "unknown fields"),
        ({"parameters": []}, "parameters"),
        ({"parameters": {"silent_option": True}}, "unknown evidence_analyst parameter"),
        ({"parameters": {"analysis_mode": "nemotron"}}, "requires model_id"),
    ],
)
def test_job_file_fails_closed_on_invalid_contract(tmp_path, overrides, message) -> None:
    path = write_job(tmp_path, **overrides)

    with pytest.raises(JobFileError, match=message):
        load_job_file(path)


def test_non_analysis_workflow_may_omit_questions(tmp_path) -> None:
    path = write_job(tmp_path, workflow="bundle_export", questions=[], parameters={})

    loaded = load_job_file(path)

    assert loaded.job.questions == ()


def test_registry_job_accepts_explicit_pdf_page_expectation(tmp_path) -> None:
    """Catches the declared source page count being rejected or lost by the job contract."""
    path = write_job(
        tmp_path,
        workflow="document_registry",
        questions=[],
        parameters={
            "column_template": "medical_reports",
            "expected_pdf_pages": {"01-endokrinologie.pdf": 2},
            "require_complete_pdf_inventory": True,
        },
    )

    loaded = load_job_file(path)

    assert loaded.job.parameters["expected_pdf_pages"] == {
        "01-endokrinologie.pdf": 2
    }
    assert loaded.job.parameters["require_complete_pdf_inventory"] is True


def test_registry_job_accepts_a_complete_hash_bound_pdf_page_review(tmp_path) -> None:
    review = {
        "page": 2,
        "source_sha256": "a" * 64,
        "method": "ocr",
        "reviewer": "ellmos-filecommander:ocr",
        "reviewed_at": "2026-09-16T07:50:00+02:00",
        "content_complete": True,
        "text": "Befund: Schilddrüse vergrößert.",
    }
    path = write_job(
        tmp_path,
        workflow="document_registry",
        questions=[],
        parameters={
            "column_template": "medical_reports",
            "expected_pdf_pages": {"01-endokrinologie.pdf": 2},
            "pdf_page_reviews": {"01-endokrinologie.pdf": [review]},
        },
    )

    loaded = load_job_file(path)

    assert loaded.job.parameters["pdf_page_reviews"] == {
        "01-endokrinologie.pdf": [review]
    }


@pytest.mark.parametrize(
    "review_patch",
    [
        {"content_complete": False},
        {"text": ""},
        {"source_sha256": "not-a-sha"},
        {"method": "guessed"},
        {"reviewer": ""},
        {"reviewed_at": "2026-09-16"},
    ],
)
def test_registry_job_rejects_incomplete_pdf_page_review(
    tmp_path, review_patch,
) -> None:
    review = {
        "page": 2,
        "source_sha256": "a" * 64,
        "method": "manual",
        "reviewer": "human:test-reviewer",
        "reviewed_at": "2026-09-16T07:50:00+02:00",
        "content_complete": True,
        "text": "Befund: Schilddrüse vergrößert.",
        **review_patch,
    }
    path = write_job(
        tmp_path,
        workflow="document_registry",
        questions=[],
        parameters={
            "column_template": "medical_reports",
            "expected_pdf_pages": {"01-endokrinologie.pdf": 2},
            "pdf_page_reviews": {"01-endokrinologie.pdf": [review]},
        },
    )

    with pytest.raises(JobFileError, match="pdf_page_reviews"):
        load_job_file(path)


def test_public_synopsis_job_rejects_internal_page_review_overlay(tmp_path) -> None:
    path = write_job(
        tmp_path,
        workflow="synopsis_merge",
        questions=[],
        parameters={
            "source_page_reviews": {
                "src_0123456789abcdef": [{
                    "page": 1,
                    "source_sha256": "a" * 64,
                    "method": "manual",
                    "reviewer": "forged",
                    "reviewed_at": "2026-09-16T07:50:00+02:00",
                    "content_complete": True,
                    "text": "Befund: frei erfunden.",
                }],
            },
        },
    )

    with pytest.raises(JobFileError, match="unknown synopsis_merge parameter"):
        load_job_file(path)


@pytest.mark.parametrize(
    "medical_purpose",
    ["source_summary", "diagnosis", "treatment_recommendation", "urgency_assessment"],
)
def test_medical_synopsis_job_accepts_an_explicit_bounded_purpose(
    tmp_path, medical_purpose,
) -> None:
    """Catches the medical purpose being lost before the authority gate can inspect it."""
    path = write_job(
        tmp_path,
        workflow="synopsis_merge",
        questions=[],
        parameters={
            "application_domain": "medical_reports",
            "medical_purpose": medical_purpose,
        },
    )

    loaded = load_job_file(path)

    assert loaded.job.parameters["medical_purpose"] == medical_purpose


@pytest.mark.parametrize("medical_purpose", ["", "general_advice", True, 1])
def test_medical_synopsis_job_rejects_an_unknown_or_untyped_purpose(
    tmp_path, medical_purpose,
) -> None:
    path = write_job(
        tmp_path,
        workflow="synopsis_merge",
        questions=[],
        parameters={
            "application_domain": "medical_reports",
            "medical_purpose": medical_purpose,
        },
    )

    with pytest.raises(JobFileError, match="medical_purpose"):
        load_job_file(path)


def test_nonmedical_synopsis_rejects_a_medical_purpose(tmp_path) -> None:
    path = write_job(
        tmp_path,
        workflow="synopsis_merge",
        questions=[],
        parameters={"medical_purpose": "source_summary"},
    )

    with pytest.raises(JobFileError, match="requires application_domain"):
        load_job_file(path)


def test_registry_job_rejects_non_boolean_complete_pdf_inventory(tmp_path) -> None:
    path = write_job(
        tmp_path,
        workflow="document_registry",
        questions=[],
        parameters={
            "column_template": "medical_reports",
            "require_complete_pdf_inventory": "yes",
        },
    )

    with pytest.raises(JobFileError, match="require_complete_pdf_inventory"):
        load_job_file(path)


@pytest.mark.parametrize(
    "expectations",
    [
        {"../outside.pdf": 2},
        {"report.txt": 2},
        {"report.pdf": True},
        {"report.pdf": 0},
        {"Report.pdf": 2, "report.pdf": 3},
    ],
)
def test_registry_job_rejects_unsafe_pdf_page_expectation(
    tmp_path, expectations
) -> None:
    """Catches path escape, non-PDF, invalid count and ambiguous declarations."""
    path = write_job(
        tmp_path,
        workflow="document_registry",
        questions=[],
        parameters={
            "column_template": "medical_reports",
            "expected_pdf_pages": expectations,
        },
    )

    with pytest.raises(JobFileError, match="expected_pdf_pages"):
        load_job_file(path)


def test_internal_job_snapshot_preserves_discovered_sources(tmp_path) -> None:
    loaded = load_job_file(write_job(tmp_path))
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(job_snapshot_payload(loaded.job)), encoding="utf-8")

    restored = load_job_snapshot(snapshot)

    assert restored == loaded.job


def test_checked_in_job_examples_follow_the_public_parser_contract() -> None:
    root = Path(__file__).resolve().parents[2]

    loaded = tuple(
        load_job_file(path).job
        for path in sorted((root / "examples" / "jobs").glob("*.json"))
    )

    assert {job.workflow for job in loaded} == {"evidence_analyst", "platform_proof"}
    assert len(loaded) == 5
