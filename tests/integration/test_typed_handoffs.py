"""A saved edge must pass one verified artifact, not a producer directory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig
from nemofold.contracts import ArtifactRecord, RunReport, RunStatus
from nemofold.voyage_runs import _verified_handoff, run_voyage
from nemofold.voyages import VoyageStore


def _voyage(tmp_path: Path, *, artifact_format: str) -> dict:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "case.txt").write_text(
        "The policy starts on 1 April 2026.\nThe yearly fee is 148 euros.\n",
        encoding="utf-8",
    )
    return {
        "name": "Verified facts handoff",
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
                "handoff": {"format": artifact_format},
            },
        ],
    }


def test_typed_handoff_reads_only_the_verified_markdown_artifact(tmp_path: Path) -> None:
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    saved = store.save(_voyage(tmp_path, artifact_format="markdown"))

    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="verified_edge",
        base_dir=tmp_path,
    )

    assert result.status == "executed"
    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    edge = dossier["steps"][1]["handoff"]
    artifact = Path(edge["path"])
    assert artifact.name == "verified_edge_01_facts.md"
    assert edge["schema"] == "nemofold.artifact-handoff.v1"
    assert edge["producer_run_id"] == "verified_edge_01"
    assert edge["format"] == "markdown"
    assert edge["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()

    ledger = json.loads(Path(result.steps[1].ledger_path or "").read_text(encoding="utf-8"))
    # The consumer scanned exactly one selected artifact, not the whole output
    # directory with duplicate notes, inventory, ledger and other artifacts.
    assert ledger["coverage"]["total_sources"] == 1


def test_missing_typed_artifact_blocks_the_consumer_and_records_why(tmp_path: Path) -> None:
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    saved = store.save(_voyage(tmp_path, artifact_format="pdf"))

    result = run_voyage(
        saved,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="missing_edge",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert result.stopped_at == 2
    assert result.steps[1].status == "handoff_blocked"
    assert result.steps[1].ledger_path is None
    assert not (tmp_path / "out" / "02-digest").exists()
    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    assert dossier["steps"][1]["errors"] == ["handoff_format_missing:pdf"]


@pytest.mark.parametrize(
    ("bad_step", "message"),
    [
        (1, "first step has no previous artifact"),
        (2, "mutually exclusive"),
        (3, "lowercase artifact label"),
    ],
)
def test_typed_handoff_rejects_ambiguous_plan_edges(
    tmp_path: Path, bad_step: int, message: str
) -> None:
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    plan = _voyage(tmp_path, artifact_format="markdown")
    if bad_step == 1:
        plan["steps"][0]["handoff"] = {"format": "markdown"}
    elif bad_step == 2:
        plan["steps"][1]["reads_previous_output"] = True
    else:
        plan["steps"][1]["handoff"] = {"format": "Markdown"}
    with pytest.raises(ValueError, match=message):
        store.save(plan)


def test_handoff_refuses_tampered_producer_bytes(tmp_path: Path) -> None:
    output = tmp_path / "producer"
    output.mkdir()
    artifact = output / "facts.md"
    artifact.write_text("Original facts", encoding="utf-8")
    original_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    report = RunReport(
        run_id="producer_01",
        idempotency_key="key",
        workflow="fact_distill",
        status=RunStatus.EXECUTED,
        artifacts=(ArtifactRecord("markdown", str(artifact), original_hash),),
    )
    artifact.write_text("Changed facts", encoding="utf-8")

    with pytest.raises(ValueError, match="handoff_hash_mismatch:markdown"):
        _verified_handoff(
            report,
            output_dir=str(output),
            artifact_format="markdown",
            privacy_mode="local_only",
        )


def test_handoff_refuses_artifact_outside_producer_output(tmp_path: Path) -> None:
    output = tmp_path / "producer"
    output.mkdir()
    outside = tmp_path / "other.md"
    outside.write_text("Not a producer output", encoding="utf-8")
    report = RunReport(
        run_id="producer_01",
        idempotency_key="key",
        workflow="fact_distill",
        status=RunStatus.EXECUTED,
        artifacts=(
            ArtifactRecord(
                "markdown", str(outside), hashlib.sha256(outside.read_bytes()).hexdigest()
            ),
        ),
    )

    with pytest.raises(ValueError, match="handoff_artifact_outside_producer:markdown"):
        _verified_handoff(
            report,
            output_dir=str(output),
            artifact_format="markdown",
            privacy_mode="local_only",
        )
