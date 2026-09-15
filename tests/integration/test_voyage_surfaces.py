"""CLI and MCP must execute the saved voyage through the same gated chain."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig
from nemofold.cli import main
from nemofold.mcp_server import MCPServerConfig, NemoFoldMCPService
from nemofold.voyages import VoyageStore


def _saved_case(tmp_path: Path, *, missing_format: bool = False) -> str:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "case.txt").write_text(
        "The policy starts on 1 April 2026.\nThe fee is 148 euros.\n",
        encoding="utf-8",
    )
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    saved = store.save(
        {
            "name": "Sourced facts to digest",
            "steps": [
                {
                    "workflow": "fact_distill",
                    "job": {
                        "schema": "nemofold.job.v1",
                        "workflow": "fact_distill",
                        "input_roots": [str(documents)],
                        "output_dir": str(tmp_path / "out" / "01-facts"),
                        "privacy_mode": "local_only",
                        "action_mode": "dry_run",
                        "parameters": {"formats": ["md"]},
                    },
                },
                {
                    "workflow": "folder_digest",
                    "job": {
                        "schema": "nemofold.job.v1",
                        "workflow": "folder_digest",
                        "input_roots": [str(documents)],
                        "output_dir": str(tmp_path / "out" / "02-digest"),
                        "privacy_mode": "local_only",
                        "action_mode": "dry_run",
                        "parameters": {},
                    },
                    "handoff": {"format": "pdf" if missing_format else "markdown"},
                },
            ],
        }
    )
    return saved["voyage_id"]


def test_cli_runs_saved_typed_voyage_and_reports_verified_edge(
    tmp_path: Path, capsys
) -> None:
    voyage_id = _saved_case(tmp_path)

    exit_code = main(
        [
            "voyage-run",
            voyage_id,
            "--base-dir",
            str(tmp_path),
            "--allow-root",
            str(tmp_path),
            "--run-id",
            "cli_edge",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "executed"
    assert payload["ok"] is True
    assert [step["status"] for step in payload["steps"]] == ["executed", "executed"]
    edge = payload["steps"][1]["handoff"]
    assert edge["schema"] == "nemofold.artifact-handoff.v1"
    assert edge["sha256"] == hashlib.sha256(Path(edge["path"]).read_bytes()).hexdigest()
    assert Path(payload["dossier_path"]).is_file()


def test_mcp_stops_saved_voyage_before_consumer_on_missing_typed_artifact(
    tmp_path: Path,
) -> None:
    voyage_id = _saved_case(tmp_path, missing_format=True)
    service = NemoFoldMCPService(
        MCPServerConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
        )
    )

    payload = service.run_voyage(voyage_id, "mcp_missing_edge")

    assert payload["ok"] is False
    assert payload["status"] == "stopped"
    assert payload["stopped_at"] == 2
    assert payload["steps"][1]["status"] == "handoff_blocked"
    assert payload["steps"][1]["errors"] == ["handoff_format_missing:pdf"]
    assert not (tmp_path / "out" / "02-digest").exists()


def test_cli_and_mcp_report_one_run_level_model_override_without_claiming_a_call(
    tmp_path: Path, capsys
) -> None:
    voyage_id = _saved_case(tmp_path)
    exit_code = main(
        [
            "voyage-run",
            voyage_id,
            "--base-dir",
            str(tmp_path),
            "--allow-root",
            str(tmp_path),
            "--run-id",
            "cli_override",
            "--model-provider",
            "openai",
            "--model",
            "gpt-5.4",
        ]
    )
    assert exit_code == 0
    cli_payload = json.loads(capsys.readouterr().out)
    service = NemoFoldMCPService(
        MCPServerConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
        )
    )
    mcp_payload = service.run_voyage(
        voyage_id,
        "mcp_override",
        model_override={"provider": "openai", "model": "gpt-5.4"},
    )

    for payload in (cli_payload, mcp_payload):
        assert payload["status"] == "executed"
        assert payload["run_level_override"] == "openai:gpt-5.4"
        assert payload["steps"][0]["model_level"] == "run-override"
        assert payload["steps"][0]["model_used"] == "nemofold-local-core"


def test_reserved_voyage_never_executes_through_mcp(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "case.txt").write_text("Fact: known.", encoding="utf-8")
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    saved = store.save(
        {
            "name": "Waiting for a future instrument",
            "status": "pending_capability",
            "missing_capability": "future_graph",
            "steps": [
                {
                    "workflow": "fact_distill",
                    "job": {
                        "schema": "nemofold.job.v1",
                        "workflow": "fact_distill",
                        "input_roots": [str(documents)],
                        "output_dir": str(tmp_path / "out"),
                        "privacy_mode": "local_only",
                        "action_mode": "dry_run",
                        "parameters": {"formats": ["md"]},
                    },
                }
            ],
        }
    )
    service = NemoFoldMCPService(
        MCPServerConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
        )
    )

    with pytest.raises(ValueError, match="pending_capability"):
        service.run_voyage(saved["voyage_id"], "mcp_reserved")
    assert not (tmp_path / "out").exists()
