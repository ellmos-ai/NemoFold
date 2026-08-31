from __future__ import annotations

from pathlib import Path

import pytest

from nemofold.drafts import DraftStore
from nemofold.job_io import SUPPORTED_WORKFLOWS
from nemofold.notebooks import ResearchNotebookStore
from nemofold.workflow_graphs import workflow_graphs


def analysis_job(tmp_path: Path) -> dict[str, object]:
    documents = tmp_path / "documents"
    documents.mkdir(exist_ok=True)
    return {
        "schema": "nemofold.job.v1",
        "workflow": "evidence_analyst",
        "input_roots": [str(documents)],
        "target_roots": [],
        "output_dir": str(tmp_path / "output"),
        "questions": ["Analyze the approved corpus."],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "model_budget_usd": 0,
        "parameters": {"max_chunks": 256, "formats": ["md"]},
    }


def test_workflow_graphs_cover_every_contract_and_mark_real_anonymization() -> None:
    graphs = {item["workflow"]: item for item in workflow_graphs()}

    assert set(graphs) == SUPPORTED_WORKFLOWS
    assert {
        name for name, graph in graphs.items() if graph["contains_anonymization"] is True
    } == {"evidence_analyst"}
    assert [node["label"] for node in graphs["evidence_analyst"]["nodes"]][:2] == [
        "Inventory",
        "Evidence bundle",
    ]
    assert any(
        node["label"] == "Version resolve" for node in graphs["folder_digest"]["nodes"]
    )


def test_draft_store_round_trip_never_persists_approval(tmp_path) -> None:
    store = DraftStore(tmp_path, (str(tmp_path),))

    draft = store.save(
        analysis_job(tmp_path),
        provider={
            "provider_id": "claude-code",
            "model": "sonnet",
            "max_output_tokens": 32_768,
            "timeout_seconds": 1_800,
        },
        name="Prepared by model",
        source="mcp",
    )
    loaded = store.load(draft["draft_id"])

    assert store.list()[0]["draft_id"] == draft["draft_id"]
    assert loaded["job"]["parameters"]["max_chunks"] == 256
    assert loaded["provider"]["provider_id"] == "claude-code"
    assert loaded["approval_state"] == {
        "external_transfer": False,
        "file_actions": False,
        "note": "Approvals are never persisted in drafts.",
    }


def test_draft_store_rejects_paths_outside_allow_roots(tmp_path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    store = DraftStore(allowed, (str(allowed),))
    job = analysis_job(allowed)
    job["input_roots"] = [str(tmp_path)]

    with pytest.raises(PermissionError, match="outside"):
        store.save(job, source="api")


def test_provider_draft_requires_the_read_only_evidence_workflow(tmp_path) -> None:
    store = DraftStore(tmp_path, (str(tmp_path),))
    job = analysis_job(tmp_path)
    job.update(
        workflow="bundle_export",
        questions=[],
        parameters={
            "bundle_format": "text",
            "bundle_name": "test_bundle",
            "include_manifest": True,
            "order": "display_name",
            "recursive": True,
        },
    )

    with pytest.raises(ValueError, match="provider drafts require"):
        store.save(
            job,
            provider={"provider_id": "ollama", "model": "qwen3"},
            source="api",
        )


def test_research_notebook_persists_investigation_without_approvals(tmp_path) -> None:
    store = ResearchNotebookStore(tmp_path, (str(tmp_path),))

    notebook = store.save(
        {
            "name": "Policy history",
            "goal": "Establish which wording was valid at each date.",
            "job": analysis_job(tmp_path),
            "provider": {
                "provider_id": "claude-code",
                "model": "sonnet",
                "max_output_tokens": 32768,
                "timeout_seconds": 1800,
            },
        }
    )
    loaded = store.load(notebook["notebook_id"])

    assert store.list()[0]["name"] == "Policy history"
    assert loaded["job"]["workflow"] == "evidence_analyst"
    assert loaded["job"]["parameters"]["max_chunks"] == 256
    assert loaded["runs"] == []
    assert loaded["approval_state"]["external_transfer"] is False
    assert loaded["approval_state"]["file_actions"] is False
