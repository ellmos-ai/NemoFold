"""G01: a personal documents folder must produce a traceable, cited tax document find."""

from __future__ import annotations

import json
from pathlib import Path

from nemofold.application import ExecutionConfig
from nemofold.contracts import RunStatus
from nemofold.g01_acceptance import (
    _g01_case,
    _write_ambiguous_fixture,
    _write_missing_fixture,
    _write_positive_fixture,
)
from nemofold.ledger import RunLedger
from nemofold.voyage_runs import run_voyage


def test_g01_document_found_with_tax_id_and_verified_handoff(tmp_path: Path) -> None:
    """Verifies that a tax document is unambiguously identified, cited, and handed off."""
    records = tmp_path / "inputs" / "personal-records"
    records.mkdir(parents=True)
    f1, f2, f3 = _write_positive_fixture(tmp_path)

    out_dir = tmp_path / "positive" / "out"
    case = _g01_case(
        f1.parent,
        out_dir,
        voyage_id="voyage_g01_test_positive",
        title="Steuernummer · fiktiver Steuerbescheid",
        min_matches=1,
        max_matches=1,
    )
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(
        case,
        config,
        run_id="g01_test_positive",
        base_dir=tmp_path,
    )

    assert result.status == "executed"
    assert len(result.steps) == 2
    assert result.completed is True

    # Step 1: corpus_query
    step1 = result.steps[0]
    assert step1.workflow == "corpus_query"
    assert step1.status == "executed"
    ledger1 = RunLedger(Path(step1.ledger_path or "").parent).load(step1.run_id)
    assert ledger1.status is RunStatus.EXECUTED
    assert ledger1.coverage is not None
    assert ledger1.coverage.total_sources == 3
    assert ledger1.coverage.read_sources == 3
    assert ledger1.coverage.cited_sources == 1

    query_json_path = next(
        Path(item.path) for item in ledger1.artifacts if item.format == "corpus-query"
    )
    query_data = json.loads(query_json_path.read_text(encoding="utf-8"))
    assert query_data["match_count"] == 1
    statement = query_data["matches"][0]["statement"]
    assert "12/345/67890" in statement
    anchor = query_data["matches"][0]["anchors"][0]
    assert anchor["line"] == 4

    query_md_path = next(
        Path(item.path) for item in ledger1.artifacts if item.format == "markdown"
    )
    query_md = query_md_path.read_text(encoding="utf-8")
    assert "12/345/67890" in query_md
    assert anchor["source_id"] in query_md

    # Step 2: folder_digest via verified typed handoff
    step2 = result.steps[1]
    assert step2.workflow == "folder_digest"
    assert step2.status == "executed"
    assert step2.handoff is not None
    assert step2.handoff["status"] == "verified"
    assert step2.handoff["format"] == "markdown"
    assert step2.handoff["producer_workflow"] == "corpus_query"
    assert step2.handoff["path"] == str(query_md_path.resolve())

    ledger2 = RunLedger(Path(step2.ledger_path or "").parent).load(step2.run_id)
    assert ledger2.status is RunStatus.EXECUTED
    assert ledger2.coverage is not None
    assert ledger2.coverage.total_sources == 1  # exactly the single handed-off markdown artifact

    digest_path = next(
        Path(item.path) for item in ledger2.artifacts if item.format == "folder-digest"
    )
    assert digest_path.is_file()


def test_g01_missing_tax_id_blocks_before_handoff(tmp_path: Path) -> None:
    """Absence of a tax document blocks the chain and generates a question."""
    f1 = _write_missing_fixture(tmp_path)

    out_dir = tmp_path / "missing-negative" / "out"
    case = _g01_case(
        f1.parent,
        out_dir,
        voyage_id="voyage_g01_test_missing",
        title="Steuernummer · kein Steuerbescheid",
        min_matches=1,
    )
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(
        case,
        config,
        run_id="g01_test_missing",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert result.stopped_at == 1
    assert len(result.steps) == 1

    step1 = result.steps[0]
    assert step1.status == "blocked"
    assert step1.errors == ("no_matches_found:Steuernummer",)

    # Step 2 was never started
    assert not (out_dir / "digest").exists()

    ledger = RunLedger(Path(step1.ledger_path or "").parent).load(step1.run_id)
    assert ledger.status is RunStatus.BLOCKED
    assert ledger.metadata.get("needs_user_input") is True

    needs_artifact = next(
        Path(item.path) for item in ledger.artifacts if item.format == "needs-user-input"
    )
    question_data = json.loads(needs_artifact.read_text(encoding="utf-8"))
    assert question_data["schema"] == "nemofold.needs-user-input.v1"
    assert question_data["questions"][0]["kind"] == "search_term"
    assert question_data["questions"][0]["field"] == "terms"


def test_g01_ambiguous_tax_id_matches_block_before_handoff(tmp_path: Path) -> None:
    """Multiple conflicting tax IDs block the chain and generate a question."""
    f1, f2 = _write_ambiguous_fixture(tmp_path)

    out_dir = tmp_path / "ambiguous-negative" / "out"
    case = _g01_case(
        f1.parent,
        out_dir,
        voyage_id="voyage_g01_test_ambiguous",
        title="Steuernummer · mehrdeutige Bescheide",
        min_matches=1,
        max_matches=1,
    )
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(
        case,
        config,
        run_id="g01_test_ambiguous",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert result.stopped_at == 1
    assert len(result.steps) == 1

    step1 = result.steps[0]
    assert step1.status == "blocked"
    assert step1.errors == ("ambiguous_matches:2>1",)

    # Step 2 was never started
    assert not (out_dir / "digest").exists()

    ledger = RunLedger(Path(step1.ledger_path or "").parent).load(step1.run_id)
    assert ledger.status is RunStatus.BLOCKED
    assert ledger.metadata.get("needs_user_input") is True

    needs_artifact = next(
        Path(item.path) for item in ledger.artifacts if item.format == "needs-user-input"
    )
    question_data = json.loads(needs_artifact.read_text(encoding="utf-8"))
    assert question_data["schema"] == "nemofold.needs-user-input.v1"
    assert question_data["questions"][0]["kind"] == "document_selection"
    assert question_data["questions"][0]["field"] == "document_choice"
