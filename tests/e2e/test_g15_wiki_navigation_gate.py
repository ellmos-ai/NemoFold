"""End-to-end tests for Gate G15 (Wissensnavigation und MetaWiki-Export).

Tests:
1. Complete MetaWiki export with valid internal links and acyclic hierarchy.
2. Broken markdown link detection blocking fail-closed with require_valid_links=True.
3. Permissive mode allowing broken markdown links when require_valid_links=False.
4. Cyclic navigation hierarchy blocking fail-closed with cyclic_wiki_hierarchy_detected.
5. Empty knowledge corpus blocking fail-closed when require_sources=True.
6. 3-step voyage (document_registry -> guide_compose -> wiki_export).
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
def g15_knowledge_dir(tmp_path: Path) -> Path:
    corpus = tmp_path / "knowledge_base"
    corpus.mkdir(parents=True, exist_ok=True)

    (corpus / "diagnostik.md").write_text(
        "# Diagnostik im Autismus-Spektrum\n\n"
        "Die standardisierte Diagnostik erfordert strukturierte Beobachtung.\n"
        "Weitere Details finden sich unter [Therapie](therapie.md) und "
        "[Foerderung](foerderung.md).\n\n"
        "Abschlussbericht folgt nach Evaluation.\n",
        encoding="utf-8",
    )
    (corpus / "therapie.md").write_text(
        "# Therapieansaetze\n\n"
        "Verhaltenstherapeutische Interventionen und TEACCH-Strukturierung.\n"
        "Siehe auch [Diagnostik](diagnostik.md) zur Ausgangslage.\n",
        encoding="utf-8",
    )
    (corpus / "foerderung.md").write_text(
        "# Foerderplaene und Alltagsstruktur\n\n"
        "Alltagsstrukturierung mit visuellen Plaenen und Symbolen.\n"
        "Querverweis zu [Therapie](therapie.md).\n",
        encoding="utf-8",
    )
    return corpus


def test_g15_metawiki_export_with_valid_links_and_hierarchy(
    g15_knowledge_dir: Path, tmp_path: Path
) -> None:
    output_dir = tmp_path / "wiki_out"
    output_dir.mkdir()

    job_payload = {
        "schema": "nemofold.job.v1",
        "workflow": "wiki_export",
        "input_roots": [str(g15_knowledge_dir)],
        "target_roots": [str(g15_knowledge_dir)],
        "output_dir": str(output_dir),
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {
            "title": "Autismus MetaWiki",
            "wiki_dir": "meta_wiki",
            "require_valid_links": True,
            "hierarchy": {
                "uebersicht": ["diagnostik", "therapie"],
                "therapie": ["foerderung"],
            },
        },
    }

    job = parse_job_payload(job_payload, base_dir=tmp_path)
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    outcome = run_job(job, config, run_id="test_g15_valid")

    assert outcome.report.status is RunStatus.EXECUTED
    wiki_folder = output_dir / "meta_wiki"
    assert (wiki_folder / "index.md").is_file()
    assert (wiki_folder / "diagnostik-md.md").is_file()
    assert (wiki_folder / "therapie-md.md").is_file()
    assert (wiki_folder / "foerderung-md.md").is_file()

    manifest_path = output_dir / "test_g15_valid.metawiki-manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "nemofold.metawiki-manifest.v1"
    assert manifest["page_count"] == 3
    assert manifest["link_verification"]["is_valid"] is True
    assert manifest["hierarchy_verification"]["is_acyclic"] is True
    assert manifest["integrity_status"] == "verified"

    overview_path = output_dir / "test_g15_valid.metawiki.md"
    assert overview_path.is_file()
    overview_text = overview_path.read_text(encoding="utf-8")
    assert "Autismus MetaWiki" in overview_text
    assert "Hierarchische Wissensgliederung" in overview_text


def test_g15_broken_wiki_links_blocked_when_required(tmp_path: Path) -> None:
    corpus = tmp_path / "broken_links_corpus"
    corpus.mkdir()
    (corpus / "seite_a.md").write_text(
        "# Seite A\n\nVerweist auf [Nicht Existent](unbekannt-12345.md) im Text.\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "broken_out"
    output_dir.mkdir()

    job_payload = {
        "schema": "nemofold.job.v1",
        "workflow": "wiki_export",
        "input_roots": [str(corpus)],
        "target_roots": [str(corpus)],
        "output_dir": str(output_dir),
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {
            "title": "Broken Links Wiki",
            "require_valid_links": True,
        },
    }

    job = parse_job_payload(job_payload, base_dir=tmp_path)
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    outcome = run_job(job, config, run_id="test_g15_broken")

    assert outcome.report.status is RunStatus.BLOCKED
    assert any("broken_wiki_links_detected" in err for err in outcome.report.errors)


def test_g15_broken_wiki_links_allowed_when_not_required(tmp_path: Path) -> None:
    corpus = tmp_path / "broken_links_corpus_permissive"
    corpus.mkdir()
    (corpus / "seite_a.md").write_text(
        "# Seite A\n\nVerweist auf [Nicht Existent](unbekannt-12345.md) im Text.\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "broken_out_permissive"
    output_dir.mkdir()

    job_payload = {
        "schema": "nemofold.job.v1",
        "workflow": "wiki_export",
        "input_roots": [str(corpus)],
        "target_roots": [str(corpus)],
        "output_dir": str(output_dir),
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {
            "title": "Permissive Wiki",
            "require_valid_links": False,
        },
    }

    job = parse_job_payload(job_payload, base_dir=tmp_path)
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    outcome = run_job(job, config, run_id="test_g15_permissive")

    assert outcome.report.status is RunStatus.EXECUTED
    manifest_path = output_dir / "test_g15_permissive.metawiki-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["link_verification"]["is_valid"] is False
    assert len(manifest["link_verification"]["broken_links"]) == 1


def test_g15_cyclic_hierarchy_blocked(g15_knowledge_dir: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "cyclic_out"
    output_dir.mkdir()

    # Cyclic hierarchy: diagnostik -> therapie -> foerderung -> diagnostik
    job_payload = {
        "schema": "nemofold.job.v1",
        "workflow": "wiki_export",
        "input_roots": [str(g15_knowledge_dir)],
        "target_roots": [str(g15_knowledge_dir)],
        "output_dir": str(output_dir),
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {
            "title": "Cyclic Wiki",
            "hierarchy": {
                "diagnostik": ["therapie"],
                "therapie": ["foerderung"],
                "foerderung": ["diagnostik"],
            },
        },
    }

    job = parse_job_payload(job_payload, base_dir=tmp_path)
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    outcome = run_job(job, config, run_id="test_g15_cyclic")

    assert outcome.report.status is RunStatus.BLOCKED
    assert any("cyclic_wiki_hierarchy_detected" in err for err in outcome.report.errors)


def test_g15_empty_knowledge_corpus_blocked(tmp_path: Path) -> None:
    empty_corpus = tmp_path / "empty_dir"
    empty_corpus.mkdir()

    output_dir = tmp_path / "empty_out"
    output_dir.mkdir()

    job_payload = {
        "schema": "nemofold.job.v1",
        "workflow": "wiki_export",
        "input_roots": [str(empty_corpus)],
        "target_roots": [str(empty_corpus)],
        "output_dir": str(output_dir),
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {
            "title": "Empty Wiki",
            "require_sources": True,
        },
    }

    job = parse_job_payload(job_payload, base_dir=tmp_path)
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    outcome = run_job(job, config, run_id="test_g15_empty")

    assert outcome.report.status is RunStatus.BLOCKED
    assert any("wiki_source_corpus_empty" in err for err in outcome.report.errors)


def test_g15_three_step_voyage_knowledge_pipeline(
    g15_knowledge_dir: Path, tmp_path: Path
) -> None:
    out1 = tmp_path / "step1_registry"
    out2 = tmp_path / "step2_guide"
    out3 = tmp_path / "step3_wiki"
    for d in (out1, out2, out3):
        d.mkdir(parents=True, exist_ok=True)

    voyage = {
        "schema": "nemofold.voyage.v1",
        "voyage_id": "vy_g15_test",
        "name": "Knowledge Navigation Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(g15_knowledge_dir)],
                    "target_roots": [str(g15_knowledge_dir)],
                    "output_dir": str(out1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "title": "Autismus Dokumentenregister",
                        "column_template": "inventory",
                        "formats": ["md", "json"],
                    },
                },
            },
            {
                "order": 2,
                "workflow": "guide_compose",
                "reads_previous_output": True,
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "guide_compose",
                    "input_roots": [str(g15_knowledge_dir)],
                    "target_roots": [str(g15_knowledge_dir)],
                    "output_dir": str(out2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "title": "Autismus Leitfaden",
                        "formats": ["md"],
                    },
                },
            },
            {
                "order": 3,
                "workflow": "wiki_export",
                "reads_previous_output": True,
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "wiki_export",
                    "input_roots": [str(g15_knowledge_dir)],
                    "target_roots": [str(g15_knowledge_dir)],
                    "output_dir": str(out3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "title": "Autismus MetaWiki",
                        "wiki_dir": "autismus_wiki",
                        "require_valid_links": True,
                        "hierarchy": {
                            "uebersicht": ["diagnostik", "therapie"],
                            "therapie": ["foerderung"],
                        },
                    },
                },
            },
        ],
    }

    config = ExecutionConfig(allowed_roots=(str(tmp_path), str(g15_knowledge_dir)))
    result = run_voyage(
        voyage,
        config=config,
        base_dir=tmp_path,
        run_id="vy_g15_run_01",
    )

    assert result.status == "executed"
    assert result.completed is True
    assert len(result.steps) == 3
    assert result.steps[0].workflow == "document_registry"
    assert result.steps[1].workflow == "guide_compose"
    assert result.steps[2].workflow == "wiki_export"
    assert (out3 / "autismus_wiki" / "index.md").is_file()
    assert (out3 / f"{result.steps[2].run_id}.metawiki-manifest.json").is_file()
