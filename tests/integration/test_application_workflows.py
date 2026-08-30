from __future__ import annotations

import json
from datetime import date

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import ActionMode, JobEnvelope, PrivacyMode
from nemofold.report_verifier import verify_run_report


def job(tmp_path, workflow: str, *, questions=(), parameters=None, input_roots=None):
    documents = tmp_path / "documents"
    documents.mkdir(exist_ok=True)
    output = tmp_path / "output"
    return JobEnvelope(
        workflow=workflow,
        input_roots=tuple(str(path) for path in (input_roots or (documents,))),
        output_dir=str(output),
        questions=tuple(questions),
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        action_mode=ActionMode.DRY_RUN,
        parameters=parameters or {},
    )


def config(tmp_path) -> ExecutionConfig:
    return ExecutionConfig(allowed_roots=(str(tmp_path),))


def test_folder_digest_writes_delta_and_coverage_artifact(tmp_path) -> None:
    current = job(tmp_path, "folder_digest", parameters={"summary_length": 1})
    (tmp_path / "documents" / "note.txt").write_text(
        "First sentence. Second sentence.", encoding="utf-8"
    )

    result = run_job(current, config(tmp_path), run_id="digest_1")

    assert result.report.status.value == "executed"
    digest = tmp_path / "output" / "digest_1.digest.md"
    assert digest.is_file()
    assert "First sentence." in digest.read_text(encoding="utf-8")
    assert verify_run_report(result.report_path).valid is True


def test_folder_digest_compares_against_a_named_prior_inventory(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    stable = documents / "stable.txt"
    changed = documents / "changed.txt"
    deleted = documents / "deleted.txt"
    stable.write_text("stable", encoding="utf-8")
    changed.write_text("old", encoding="utf-8")
    deleted.write_text("remove", encoding="utf-8")
    first = job(tmp_path, "folder_digest")
    initial = run_job(first, config(tmp_path), run_id="digest_base")
    assert initial.report.status.value == "executed"

    changed.write_text("new", encoding="utf-8")
    deleted.unlink()
    (documents / "added.txt").write_text("added", encoding="utf-8")
    follow_up = job(
        tmp_path,
        "folder_digest",
        parameters={"since_run_id": "digest_base"},
    )
    result = run_job(follow_up, config(tmp_path), run_id="digest_delta")

    assert result.report.status.value == "executed"
    assert len(result.report.metadata["new_source_ids"]) == 1
    assert len(result.report.metadata["changed_source_ids"]) == 1
    assert len(result.report.metadata["unchanged_source_ids"]) == 1
    assert len(result.report.metadata["deleted_source_ids"]) == 1
    digest = (tmp_path / "output" / "digest_delta.digest.md").read_text(encoding="utf-8")
    assert "Deleted since prior run" in digest


def test_evidence_analyst_answers_each_question_with_exact_local_quote(tmp_path) -> None:
    current = job(
        tmp_path,
        "evidence_analyst",
        questions=("When does coverage begin?", "When does coverage end?"),
        parameters={"max_chunks": 3, "formats": ["md", "txt"]},
    )
    (tmp_path / "documents" / "policy.txt").write_text(
        "Coverage begins on 1 April 2026. Coverage ends on 31 December 2026.",
        encoding="utf-8",
    )

    result = run_job(current, config(tmp_path), run_id="analysis_1")

    assert result.report.status.value == "executed"
    assert result.report.coverage.cited_sources == 1
    assert result.report.metadata["answered_questions"] == 2
    report = (tmp_path / "output" / "analysis_1.md").read_text(encoding="utf-8")
    assert "policy.txt" in report
    assert "Coverage begins on 1 April 2026." in report
    assert "section lines 1-1" in report
    analysis = json.loads(
        (tmp_path / "output" / "analysis_1.analysis.json").read_text(encoding="utf-8")
    )
    assert analysis["schema"] == "nemofold.analysis.v1"
    assert len(analysis["answers"]) == 2
    assert verify_run_report(result.report_path).valid is True


def test_evidence_analyst_marks_conflicting_numeric_passages(tmp_path) -> None:
    current = job(
        tmp_path,
        "evidence_analyst",
        questions=("What is the deductible?",),
        parameters={"max_chunks": 4, "conflict_scan": True, "formats": ["md"]},
    )
    (tmp_path / "documents" / "old.txt").write_text(
        "The deductible is 500 euros.", encoding="utf-8"
    )
    (tmp_path / "documents" / "new.txt").write_text(
        "The deductible is 750 euros.", encoding="utf-8"
    )

    result = run_job(current, config(tmp_path), run_id="analysis_conflict")

    analysis = json.loads(
        (tmp_path / "output" / "analysis_conflict.analysis.json").read_text(
            encoding="utf-8"
        )
    )
    claim = analysis["answers"][0]["claim"]
    assert result.report.status.value == "executed"
    assert result.report.metadata["potential_conflicts"] == 1
    assert claim["conflict_status"] == "potential_conflict"
    assert len(claim["evidence"]) == 2


def test_version_resolver_prefers_explicit_issue_date_over_file_time(tmp_path) -> None:
    current = job(tmp_path, "version_resolver", parameters={"as_of": "2026-08-30"})
    old = tmp_path / "documents" / "policy_v1_2025-01-01.txt"
    new = tmp_path / "documents" / "policy_v2_2026-03-01.txt"
    old.write_text("Old wording", encoding="utf-8")
    new.write_text("New wording", encoding="utf-8")
    old.touch()
    new.touch()

    result = run_job(current, config(tmp_path), run_id="versions_1")

    assert result.report.status.value == "executed"
    assert result.report.metadata["selected_display_name"] == new.name
    assert result.report.metadata["version_basis"] == "issue_date"
    comparison = json.loads(
        (tmp_path / "output" / "versions_1.versions.json").read_text(encoding="utf-8")
    )
    assert comparison["as_of"] == date(2026, 8, 30).isoformat()
    assert comparison["selected"]["display_name"] == new.name
    assert comparison["comparison"]["added_lines"] == ["New wording"]


def test_version_resolver_groups_families_and_uses_explicit_validity(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    for name, content in (
        ("policy_v1.txt", "old policy"),
        ("policy_v2.txt", "current policy"),
        ("guide_v1.txt", "old guide"),
        ("guide_v2.txt", "future guide"),
    ):
        (documents / name).write_text(content, encoding="utf-8")
    current = job(
        tmp_path,
        "version_resolver",
        parameters={
            "as_of": "2026-08-30",
            "validity_fields": {
                "policy_v1.txt": {"valid_until": "2025-12-31"},
                "policy_v2.txt": {"valid_from": "2026-01-01"},
                "guide_v1.txt": {"valid_until": "2026-12-31"},
                "guide_v2.txt": {"valid_from": "2027-01-01"},
            },
        },
    )

    result = run_job(current, config(tmp_path), run_id="versions_families")

    payload = json.loads(
        (tmp_path / "output" / "versions_families.versions.json").read_text(
            encoding="utf-8"
        )
    )
    selected = {
        family["family"]: family["selected"]["display_name"]
        for family in payload["families"]
    }
    assert result.report.status.value == "executed"
    assert result.report.metadata["family_count"] == 2
    assert selected == {"guide": "guide_v1.txt", "policy": "policy_v2.txt"}


def test_report_studio_renders_a_validated_analysis_contract(tmp_path) -> None:
    analysis = tmp_path / "analysis.json"
    analysis.write_text(
        json.dumps(
            {
                "schema": "nemofold.analysis.v1",
                "title": "Validated case",
                "answers": [
                    {
                        "question": "What is confirmed?",
                        "claim": {
                            "statement": "The date is confirmed.",
                            "uncertainty": 0.0,
                            "conflict_status": "none",
                            "evidence": [
                                {
                                    "source_id": "src_a",
                                    "quote": "Confirmed date",
                                    "section": "src_a:000000",
                                }
                            ],
                        },
                        "verified": True,
                    }
                ],
                "coverage": {
                    "total_sources": 1,
                    "read_sources": 1,
                    "cited_sources": 1,
                    "unread_source_ids": [],
                    "uncited_read_source_ids": [],
                },
                "source_labels": {"src_a": "case.txt"},
            }
        ),
        encoding="utf-8",
    )
    current = job(
        tmp_path,
        "report_studio",
        parameters={"formats": ["md", "txt", "pdf", "docx", "odt"]},
        input_roots=(analysis,),
    )

    result = run_job(current, config(tmp_path), run_id="report_1")

    assert result.report.status.value == "executed"
    assert len(result.report.artifacts) == 6
    assert all(record.status == "written" for record in result.report.artifacts)
    assert verify_run_report(result.report_path).valid is True


def test_platform_proof_remains_explicitly_offline_without_runtime(tmp_path) -> None:
    current = job(
        tmp_path,
        "platform_proof",
        questions=("What is supported?",),
    )
    (tmp_path / "documents" / "proof.txt").write_text(
        "The offline path is supported.", encoding="utf-8"
    )

    result = run_job(current, config(tmp_path), run_id="proof_1")

    assert result.report.status.value == "executed"
    assert result.report.metadata["cloud_proof"] is False
    assert result.report.metadata["evidence_level"] == "offline"
    assert "nemoclaw_live" not in result.report.actions
    assert verify_run_report(result.report_path).valid is True


def test_storage_policy_dry_run_writes_plan_without_moving_files(tmp_path) -> None:
    (tmp_path / "documents").mkdir()
    source = tmp_path / "documents" / "Case.TXT"
    source.write_text("content", encoding="utf-8")
    target = tmp_path / "archive"
    target.mkdir()
    current = JobEnvelope(
        workflow="storage_policy",
        input_roots=(str(tmp_path / "documents"),),
        target_roots=(str(target),),
        output_dir=str(tmp_path / "output"),
        action_mode=ActionMode.DRY_RUN,
        parameters={
            "naming_template": "ARCHIVE_{stem}{suffix}",
            "allowed_extensions": [".txt"],
        },
    )

    result = run_job(current, config(tmp_path), run_id="policy_1")

    assert result.report.status.value == "executed"
    assert source.is_file()
    assert not (target / "ARCHIVE_Case.txt").exists()
    plan = json.loads(
        (tmp_path / "output" / "policy_1.action-plan.json").read_text(encoding="utf-8")
    )
    assert plan["plans"][0]["allowed"] is True
    assert plan["plans"][0]["target"].endswith("ARCHIVE_Case.txt")


def test_smart_inbox_apply_moves_every_file_with_journal_and_undo_receipts(tmp_path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "one.txt").write_text("one", encoding="utf-8")
    (inbox / "two.md").write_text("two", encoding="utf-8")
    text_target = tmp_path / "text"
    markdown_target = tmp_path / "markdown"
    text_target.mkdir()
    markdown_target.mkdir()
    current = JobEnvelope(
        workflow="smart_inbox",
        input_roots=(str(inbox),),
        target_roots=(str(text_target), str(markdown_target)),
        output_dir=str(tmp_path / "output"),
        action_mode=ActionMode.APPLY,
        parameters={
            "routes": [
                {"suffixes": [".txt"], "target_root": 0},
                {"suffixes": [".md"], "target_root": 1},
            ],
            "allowed_extensions": [".txt", ".md"],
        },
    )
    approved = ExecutionConfig(
        allowed_roots=(str(tmp_path),),
        apply_actions_allowed=True,
    )

    result = run_job(current, approved, run_id="inbox_1")

    assert result.report.status.value == "executed"
    assert (text_target / "one.txt").is_file()
    assert (markdown_target / "two.md").is_file()
    assert not any(inbox.iterdir())
    receipts = json.loads(
        (tmp_path / "output" / "inbox_1.undo-receipts.json").read_text(encoding="utf-8")
    )
    assert len(receipts["receipts"]) == 2
    assert all(item["status"] == "available" for item in receipts["receipts"])
    assert verify_run_report(result.report_path).valid is True


def test_smart_inbox_collision_blocks_the_entire_batch_before_any_move(tmp_path) -> None:
    inbox = tmp_path / "inbox"
    target = tmp_path / "target"
    inbox.mkdir()
    target.mkdir()
    (inbox / "a.txt").write_text("new a", encoding="utf-8")
    (inbox / "b.txt").write_text("new b", encoding="utf-8")
    (target / "b.txt").write_text("existing b", encoding="utf-8")
    current = JobEnvelope(
        workflow="smart_inbox",
        input_roots=(str(inbox),),
        target_roots=(str(target),),
        output_dir=str(tmp_path / "output"),
        action_mode=ActionMode.APPLY,
        parameters={"routes": [{"suffixes": [".txt"], "target_root": 0}]},
    )

    result = run_job(
        current,
        ExecutionConfig(allowed_roots=(str(tmp_path),), apply_actions_allowed=True),
        run_id="inbox_blocked",
    )

    assert result.report.status.value == "blocked"
    assert "target_collision" in result.report.errors
    assert (inbox / "a.txt").is_file()
    assert (inbox / "b.txt").is_file()
    assert not (target / "a.txt").exists()
