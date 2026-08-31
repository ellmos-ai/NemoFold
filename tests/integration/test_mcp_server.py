from __future__ import annotations

import asyncio

import pytest

from nemofold.application import ExecutionConfig
from nemofold.mcp_server import MCPServerConfig, NemoFoldMCPService, build_mcp_server


def test_mcp_server_exposes_one_bounded_tool_surface(tmp_path) -> None:
    server = build_mcp_server(
        MCPServerConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
        )
    )

    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {
        "nemofold_capabilities",
        "nemofold_anonymize",
        "nemofold_preview",
        "nemofold_run",
        "nemofold_analyze_with_provider",
        "nemofold_save_draft",
        "nemofold_list_drafts",
        "nemofold_list_voyages",
        "nemofold_copy_voyage_preset",
        "nemofold_verify_report",
    }
    # The surface stays bounded and self-describing: capabilities must name the
    # same tools the server actually exposes.
    service = NemoFoldMCPService(
        MCPServerConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
        )
    )
    assert set(service.capabilities()["tools"]) == {tool.name for tool in tools}


def test_mcp_anonymizer_is_local_bounded_and_keeps_no_reverse_map(tmp_path) -> None:
    service = NemoFoldMCPService(
        MCPServerConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
        )
    )

    result = service.anonymize(
        "Mail analyst@example.org about Lukas Example.",
        ["Lukas Example"],
    )

    assert result["text"] == "Mail <EMAIL_001> about <TERM_001>."
    assert result["replacement_counts"] == {"EMAIL": 1, "TERM": 1}
    assert result["raw_mapping_stored"] is False
    assert result["transfer_performed"] is False


def test_mcp_preview_uses_the_same_job_contract_and_root_gate(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "case.txt").write_text("Evidence.", encoding="utf-8")
    service = NemoFoldMCPService(
        MCPServerConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
        )
    )
    job = {
        "schema": "nemofold.job.v1",
        "workflow": "folder_digest",
        "input_roots": ["documents"],
        "output_dir": "output",
        "questions": [],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {},
    }

    result = service.preview(job, "mcp_preview")

    assert result["report"]["status"] == "planned"
    assert result["report"]["workflow"] == "folder_digest"


def test_mcp_can_prepare_a_browser_draft_and_assign_run_ids_automatically(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "case.txt").write_text("Evidence.", encoding="utf-8")
    service = NemoFoldMCPService(
        MCPServerConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
        )
    )
    job = {
        "schema": "nemofold.job.v1",
        "workflow": "evidence_analyst",
        "input_roots": ["documents"],
        "output_dir": "output",
        "questions": ["What is supported?"],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {"max_chunks": 64, "formats": ["md"]},
    }

    draft = service.save_draft(job, name="MCP handoff")
    preview = service.preview(job)

    assert service.list_drafts()["drafts"][0]["name"] == "MCP handoff"
    assert draft["draft"]["approval_state"]["external_transfer"] is False
    assert preview["report"]["run_id"].startswith("mcp_")


def test_mcp_report_verifier_rejects_paths_outside_allow_roots(tmp_path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    service = NemoFoldMCPService(
        MCPServerConfig(
            base_dir=allowed,
            execution=ExecutionConfig(allowed_roots=(str(allowed),)),
        )
    )

    with pytest.raises(PermissionError, match="outside"):
        service.verify_report(str(tmp_path / "outside" / "report.json"))
