"""End-to-end tests for Gate G16 (Interrater-Uebereinstimmung und D-030).

Tests:
1. rater_race standalone execution with two independent coding sheets.
2. rater_race fails closed when questionnaire items are omitted in a coding sheet.
3. rater_race fails closed when undeclared codes outside the scheme are supplied.
4. rater_race fails closed when the coding scheme is invalid or empty.
5. rater_race honestly handles single-class degenerate coding (kappa is None with note).
6. 3-step voyage (document_registry -> rater_race -> folder_digest).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.job_io import parse_job_payload
from nemofold.voyage_runs import run_voyage


@pytest.fixture
def g16_corpus_dir(tmp_path: Path) -> Path:
    corpus = tmp_path / "questionnaires"
    corpus.mkdir(parents=True, exist_ok=True)
    for i in range(1, 11):
        (corpus / f"item_{i:02d}.txt").write_text(
            f"Fragebogen Item {i:02d}: Klienten-Feedback zur Massnahme.\n",
            encoding="utf-8",
        )
    return corpus


def test_g16_rater_race_standalone_positive(g16_corpus_dir: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "rater_out"
    output_dir.mkdir()

    coding_scheme = {
        "hoch": ["hoch", "sehr gut", "ueberdurchschnittlich"],
        "mittel": ["mittel", "durchschnittlich", "ausreichend"],
        "niedrig": ["niedrig", "unzureichend", "schlecht"],
    }
    coding_a = {f"item_{i:02d}.txt": "hoch" if i <= 7 else "mittel" for i in range(1, 11)}
    coding_b = {
        f"item_{i:02d}.txt": "hoch" if i <= 6 else ("mittel" if i <= 9 else "niedrig")
        for i in range(1, 11)
    }

    job_payload = {
        "schema": "nemofold.job.v1",
        "workflow": "rater_race",
        "input_roots": [str(g16_corpus_dir)],
        "target_roots": [str(g16_corpus_dir)],
        "output_dir": str(output_dir),
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {
            "title": "Interrater Vergleich 10 Items",
            "coding_scheme": coding_scheme,
            "rater_a": "Dr. Weber",
            "rater_b": "Dr. Lindemann",
            "coding_a": coding_a,
            "coding_b": coding_b,
            "formats": ["md"],
        },
    }

    job = parse_job_payload(job_payload, base_dir=tmp_path)
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    outcome = run_job(job, config, run_id="test_g16_pos")

    assert outcome.report.status is RunStatus.EXECUTED
    json_path = output_dir / "test_g16_pos.interrater.json"
    xlsx_path = output_dir / "test_g16_pos.interrater.xlsx"
    md_path = output_dir / "test_g16_pos_interrater.md"

    assert json_path.is_file()
    assert xlsx_path.is_file()
    assert md_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["item_count"] == 10
    assert payload["agreed"] == 8
    assert payload["disagreed"] == 2
    assert payload["percent_agreement"] == 80.0
    assert payload["cohens_kappa"] is not None
    assert payload["cohens_kappa"] > 0.4
    assert payload["rater_a"] == "Dr. Weber"
    assert payload["rater_b"] == "Dr. Lindemann"


def test_g16_rater_race_omitted_item_blocks_fail_closed(
    g16_corpus_dir: Path, tmp_path: Path
) -> None:
    output_dir = tmp_path / "rater_omitted_out"
    output_dir.mkdir()

    coding_scheme = {"hoch": ["hoch"], "niedrig": ["niedrig"]}
    # Omit item_10.txt in coding_a
    coding_a = {f"item_{i:02d}.txt": "hoch" for i in range(1, 10)}
    coding_b = {f"item_{i:02d}.txt": "hoch" for i in range(1, 11)}

    job_payload = {
        "schema": "nemofold.job.v1",
        "workflow": "rater_race",
        "input_roots": [str(g16_corpus_dir)],
        "target_roots": [str(g16_corpus_dir)],
        "output_dir": str(output_dir),
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {
            "title": "Omitted Item Test",
            "coding_scheme": coding_scheme,
            "rater_a": "Dr. Weber",
            "rater_b": "Dr. Lindemann",
            "coding_a": coding_a,
            "coding_b": coding_b,
            "formats": ["md"],
        },
    }

    job = parse_job_payload(job_payload, base_dir=tmp_path)
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    outcome = run_job(job, config, run_id="test_g16_omitted")

    assert outcome.report.status is RunStatus.BLOCKED
    assert any("omits" in str(err) for err in outcome.report.errors)


def test_g16_rater_race_undeclared_code_blocks_fail_closed(
    g16_corpus_dir: Path, tmp_path: Path
) -> None:
    output_dir = tmp_path / "rater_undeclared_out"
    output_dir.mkdir()

    coding_scheme = {"positiv": ["positiv"], "negativ": ["negativ"]}
    coding_a = {f"item_{i:02d}.txt": "positiv" for i in range(1, 11)}
    # item_05 has undeclared code "unbekannt"
    coding_b = {
        f"item_{i:02d}.txt": "positiv" if i != 5 else "unbekannt" for i in range(1, 11)
    }

    job_payload = {
        "schema": "nemofold.job.v1",
        "workflow": "rater_race",
        "input_roots": [str(g16_corpus_dir)],
        "target_roots": [str(g16_corpus_dir)],
        "output_dir": str(output_dir),
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {
            "title": "Undeclared Code Test",
            "coding_scheme": coding_scheme,
            "rater_a": "Dr. Weber",
            "rater_b": "Dr. Lindemann",
            "coding_a": coding_a,
            "coding_b": coding_b,
            "formats": ["md"],
        },
    }

    job = parse_job_payload(job_payload, base_dir=tmp_path)
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    outcome = run_job(job, config, run_id="test_g16_undeclared")

    assert outcome.report.status is RunStatus.BLOCKED
    assert any("undeclared" in str(err) for err in outcome.report.errors)


def test_g16_rater_race_invalid_scheme_blocks(
    g16_corpus_dir: Path, tmp_path: Path
) -> None:
    output_dir = tmp_path / "rater_invalid_scheme_out"
    output_dir.mkdir()

    coding_a = {f"item_{i:02d}.txt": "positiv" for i in range(1, 11)}
    coding_b = {f"item_{i:02d}.txt": "positiv" for i in range(1, 11)}

    job_payload = {
        "schema": "nemofold.job.v1",
        "workflow": "rater_race",
        "input_roots": [str(g16_corpus_dir)],
        "target_roots": [str(g16_corpus_dir)],
        "output_dir": str(output_dir),
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {
            "title": "Invalid Scheme Test",
            "coding_scheme": {},  # empty scheme
            "rater_a": "Dr. Weber",
            "rater_b": "Dr. Lindemann",
            "coding_a": coding_a,
            "coding_b": coding_b,
            "formats": ["md"],
        },
    }

    job = parse_job_payload(job_payload, base_dir=tmp_path)
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    outcome = run_job(job, config, run_id="test_g16_invalid_scheme")

    assert outcome.report.status is RunStatus.BLOCKED
    assert any("invalid_coding_scheme" in str(err) for err in outcome.report.errors)


def test_g16_rater_race_single_class_degenerate_honest_kappa_none(
    g16_corpus_dir: Path, tmp_path: Path
) -> None:
    output_dir = tmp_path / "rater_degenerate_out"
    output_dir.mkdir()

    coding_scheme = {"positiv": ["positiv"], "negativ": ["negativ"]}
    coding_a = {f"item_{i:02d}.txt": "positiv" for i in range(1, 11)}
    coding_b = {f"item_{i:02d}.txt": "positiv" for i in range(1, 11)}

    job_payload = {
        "schema": "nemofold.job.v1",
        "workflow": "rater_race",
        "input_roots": [str(g16_corpus_dir)],
        "target_roots": [str(g16_corpus_dir)],
        "output_dir": str(output_dir),
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {
            "title": "Degenerate Single Class Test",
            "coding_scheme": coding_scheme,
            "rater_a": "Dr. Weber",
            "rater_b": "Dr. Lindemann",
            "coding_a": coding_a,
            "coding_b": coding_b,
            "formats": ["md"],
        },
    }

    job = parse_job_payload(job_payload, base_dir=tmp_path)
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    outcome = run_job(job, config, run_id="test_g16_degenerate")

    assert outcome.report.status is RunStatus.EXECUTED
    json_path = output_dir / "test_g16_degenerate.interrater.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["cohens_kappa"] is None
    assert payload["percent_agreement"] == 100.0
    assert "kappa_note" in payload
    assert "single category" in payload["kappa_note"]


def test_g16_three_step_voyage(g16_corpus_dir: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "voyage_ws"
    workspace.mkdir()
    out1 = workspace / "step1_registry"
    out2 = workspace / "step2_rater"
    out3 = workspace / "step3_digest"
    for d in (out1, out2, out3):
        d.mkdir(parents=True, exist_ok=True)

    coding_scheme = {"positiv": ["gut"], "negativ": ["schlecht"]}
    coding_a = {f"item_{i:02d}.txt": "positiv" for i in range(1, 11)}
    coding_b = {
        f"item_{i:02d}.txt": "positiv" if i != 10 else "negativ" for i in range(1, 11)
    }

    voyage = {
        "schema": "nemofold.voyage.v1",
        "voyage_id": "vy_g16_e2e",
        "name": "Interrater 3-Step Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(g16_corpus_dir)],
                    "target_roots": [str(g16_corpus_dir)],
                    "output_dir": str(out1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "title": "Registry",
                        "column_template": "inventory",
                    },
                },
            },
            {
                "order": 2,
                "workflow": "rater_race",
                "reads_previous_output": False,
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "rater_race",
                    "input_roots": [str(g16_corpus_dir)],
                    "target_roots": [str(g16_corpus_dir)],
                    "output_dir": str(out2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "title": "Rater Race Voyage Step",
                        "coding_scheme": coding_scheme,
                        "rater_a": "Dr. Weber",
                        "rater_b": "Dr. Lindemann",
                        "coding_a": coding_a,
                        "coding_b": coding_b,
                        "formats": ["md"],
                    },
                },
            },
            {
                "order": 3,
                "workflow": "folder_digest",
                "reads_previous_output": True,
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(out2)],
                    "output_dir": str(out3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"summary_length": 3},
                },
            },
        ],
    }

    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(voyage, config=config, base_dir=workspace, run_id="vy_g16_run")

    assert result.status == "executed"
    assert result.completed is True
    assert len(result.steps) == 3
