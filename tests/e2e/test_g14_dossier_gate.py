"""Tests for Gate G14: Dossier and Briefing (Ellmos UC 25)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.g14_acceptance import FakeSearchAdapter, SparseSearchAdapter
from nemofold.job_io import parse_job_payload
from nemofold.voyage_runs import run_voyage


def _job(tmp_path: Path, workflow: str, **parameters):
    return parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": workflow,
            "input_roots": [str(tmp_path / "leer")],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": parameters,
        },
        base_dir=tmp_path,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "leer").mkdir(parents=True, exist_ok=True)
    (tmp_path / "leer" / "info.txt").write_text("Kontextnotiz", encoding="utf-8")
    return tmp_path


def test_execute_briefing_complete_path(workspace: Path) -> None:
    job = _job(
        workspace,
        "briefing",
        subject="Dr. Almut Schrenk",
        question="Welche diagnostischen Schwerpunkte bietet die Praxis?",
        meeting_context="Fachgespräch Schilddrüsendiagnostik",
        queries=["Dr. Almut Schrenk Spezialisierung", "Praxis Schrenk Diagnostik"],
        min_sources=2,
        mock_adapter=FakeSearchAdapter(),
        web_search_approved=True,
    )

    config = ExecutionConfig(allowed_roots=(str(workspace),), web_search_allowed=True)
    result = run_job(job, config, run_id="briefing_pos_01")

    assert result.report.status is RunStatus.EXECUTED
    out_dir = workspace / "out"
    json_path = out_dir / "briefing_pos_01.briefing.json"
    md_path = out_dir / "briefing_pos_01.briefing.md"
    assert json_path.is_file()
    assert md_path.is_file()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["schema"] == "nemofold.briefing.v1"
    assert data["subject"] == "Dr. Almut Schrenk"
    assert data["status"] == "complete_briefing"
    assert data["is_limited"] is False
    assert len(data["facts"]) >= 2
    assert len(data["inferences"]) >= 2
    assert len(data["uncertainties_and_open_points"]) >= 2

    # Check strict separation
    fact_ids = [f["fact_id"] for f in data["facts"]]
    for inf in data["inferences"]:
        for fid in inf["grounded_in_facts"]:
            assert fid in fact_ids

    # Check Markdown sections
    md_content = md_path.read_text(encoding="utf-8")
    assert "## 1. Fragestellung und Kontext" in md_content
    assert "## 2. Recherchequellen" in md_content
    assert "## 3. Belegte Fakten (Synthese)" in md_content
    assert "## 4. Schlussfolgerungen" in md_content
    assert "## 5. Unsicherheiten und offene Punkte" in md_content
    assert "Vollständiges Briefing" in md_content


def test_execute_briefing_sparse_sources_produces_limited_briefing(workspace: Path) -> None:
    job = _job(
        workspace,
        "briefing",
        subject="Archivbestand Theta",
        question="Untersuchung historischer Bestände",
        queries=["Archiv Theta"],
        min_sources=3,
        mock_adapter=SparseSearchAdapter(),
        web_search_approved=True,
    )

    config = ExecutionConfig(allowed_roots=(str(workspace),), web_search_allowed=True)
    result = run_job(job, config, run_id="briefing_sparse_01")

    # Honest execution without throwing, but explicitly limited (Ellmos UC 25 negative case)
    assert result.report.status is RunStatus.EXECUTED
    out_dir = workspace / "out"
    json_path = out_dir / "briefing_sparse_01.briefing.json"
    md_path = out_dir / "briefing_sparse_01.briefing.md"
    assert json_path.is_file()
    assert md_path.is_file()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["status"] == "limited_briefing"
    assert data["is_limited"] is True
    assert any("Unzureichende Quellenlage" in r for r in data["limitation_reasons"])
    assert any(
        p["issue"] == "Unzureichende Quellendichte"
        for p in data["uncertainties_and_open_points"]
    )

    md_content = md_path.read_text(encoding="utf-8")
    assert "Begrenztes Briefing" in md_content
    assert "Unzureichende Quellenlage" in md_content
    assert "Falsche Vollständigkeit wird vermieden." in md_content


def test_execute_briefing_sparse_sources_strictly_blocked_when_required(
    workspace: Path,
) -> None:
    job = _job(
        workspace,
        "briefing",
        subject="Archivbestand Theta",
        question="Untersuchung historischer Bestände",
        queries=["Archiv Theta"],
        min_sources=3,
        require_sufficient_sources=True,
        mock_adapter=SparseSearchAdapter(),
        web_search_approved=True,
    )

    config = ExecutionConfig(allowed_roots=(str(workspace),), web_search_allowed=True)
    result = run_job(job, config, run_id="briefing_sparse_blocked")

    assert result.report.status is RunStatus.BLOCKED
    assert "insufficient_sources_for_briefing" in result.report.errors


def test_execute_briefing_unapproved_search_blocked(workspace: Path) -> None:
    job = _job(
        workspace,
        "briefing",
        subject="Dr. Almut Schrenk",
        queries=["Praxis Schrenk"],
        mock_adapter=FakeSearchAdapter(),
        web_search_approved=False,
    )

    config = ExecutionConfig(allowed_roots=(str(workspace),), web_search_allowed=True)
    result = run_job(job, config, run_id="briefing_unapproved")

    assert result.report.status is RunStatus.BLOCKED
    assert "web_search_not_approved_for_this_call" in result.report.errors


def test_execute_briefing_sensitive_query_blocked_by_preflight(workspace: Path) -> None:
    job = _job(
        workspace,
        "briefing",
        subject="Privatrecherche",
        queries=["kontakt almut.schrenk@praxis-berlin.invalid und +49 30 12345678"],
        mock_adapter=FakeSearchAdapter(),
        web_search_approved=True,
    )

    config = ExecutionConfig(allowed_roots=(str(workspace),), web_search_allowed=True)
    result = run_job(job, config, run_id="briefing_sensitive")

    assert result.report.status is RunStatus.BLOCKED
    assert any("pseudonymization preflight" in err for err in result.report.errors)


def test_execute_briefing_without_subject_fails(workspace: Path) -> None:
    job = _job(
        workspace,
        "briefing",
        subject="",
        queries=["Thema ohne Betreff"],
        mock_adapter=FakeSearchAdapter(),
        web_search_approved=True,
    )

    config = ExecutionConfig(allowed_roots=(str(workspace),), web_search_allowed=True)
    result = run_job(job, config, run_id="briefing_no_subj")

    assert result.report.status is RunStatus.FAILED
    assert any("a briefing needs a declared subject" in err for err in result.report.errors)


def test_execute_dossier_includes_briefing_artifacts(workspace: Path) -> None:
    job = _job(
        workspace,
        "dossier",
        subject="Dr. Almut Schrenk",
        queries=["Dr. Almut Schrenk"],
        min_sources=1,
        mock_adapter=FakeSearchAdapter(),
        web_search_approved=True,
    )

    config = ExecutionConfig(allowed_roots=(str(workspace),), web_search_allowed=True)
    result = run_job(job, config, run_id="dossier_plus_briefing")

    assert result.report.status is RunStatus.EXECUTED
    out_dir = workspace / "out"
    assert (out_dir / "dossier_plus_briefing.dossier.json").is_file()
    assert (out_dir / "dossier_plus_briefing.briefing.json").is_file()
    assert (out_dir / "dossier_plus_briefing.briefing.md").is_file()


def test_g14_3step_voyage_with_document_qa(workspace: Path) -> None:
    s1_out = workspace / "voy_s1"
    s2_out = workspace / "voy_s2"
    s3_out = workspace / "voy_s3"

    plan = {
        "voyage_id": "vy_g14_test",
        "name": "g14_voyage_test",
        "steps": [
            {
                "order": 1,
                "workflow": "web_research",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "web_research",
                    "input_roots": [str(workspace / "leer")],
                    "output_dir": str(s1_out),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "queries": ["Dr. Almut Schrenk Diagnostik"],
                        "max_results": 2,
                        "mock_adapter": FakeSearchAdapter(),
                        "web_search_approved": True,
                    },
                },
            },
            {
                "order": 2,
                "workflow": "briefing",
                "reads_previous_output": True,
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "briefing",
                    "input_roots": [str(s1_out)],
                    "output_dir": str(s2_out),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "subject": "Dr. Almut Schrenk",
                        "question": "Diagnostik und Spezialisierungen",
                        "min_sources": 1,
                    },
                },
            },
            {
                "order": 3,
                "workflow": "document_qa",
                "handoff": {"format": "briefing-markdown"},
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_qa",
                    "input_roots": [str(s2_out)],
                    "output_dir": str(s3_out),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "required_sections": [
                            "Fragestellung",
                            "Recherchequellen",
                            "Synthese",
                            "Schlussfolgerungen",
                            "Unsicherheiten und offene Punkte",
                        ],
                        "disallow_unbound_fields": True,
                        "min_words": 15,
                    },
                },
            },
        ],
    }

    config = ExecutionConfig(allowed_roots=(str(workspace),), web_search_allowed=True)
    res = run_voyage(plan, config, run_id="vy_g14_test", base_dir=workspace)

    assert res.status == "executed"
    assert len(res.steps) == 3
    assert res.steps[0].workflow == "web_research" and res.steps[0].status == "executed"
    assert res.steps[1].workflow == "briefing" and res.steps[1].status == "executed"
    assert res.steps[2].workflow == "document_qa" and res.steps[2].status == "executed"
    assert (s3_out / f"{res.steps[2].run_id}.publication-package.json").is_file()
