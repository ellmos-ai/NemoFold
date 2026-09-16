from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nemofold.cli import main
from nemofold.g03_acceptance import G03AcceptanceError, run_g03_acceptance_bundle


def test_g03_acceptance_bundle_verifies_positive_and_negative_runs(tmp_path: Path) -> None:
    bundle = run_g03_acceptance_bundle(
        tmp_path / "g03-evidence",
    )

    assert bundle.verification["verified_evidence_gates"] == ["G03"]
    assert bundle.verification["verified_done_gates"] == []
    register = json.loads(bundle.register_path.read_text(encoding="utf-8"))
    g03 = next(gate for gate in register["gates"] if gate["gate_id"] == "G03")
    assert g03["status"] == "partial"
    assert g03["evidence"]["test_nodes"] == []
    assert len(g03["evidence"]["run_receipts"]) == 1
    receipt = g03["evidence"]["run_receipts"][0]
    assert receipt["run_id"] == "g03_acceptance_positive_02"

    # Verify negative path 1 (unreadable)
    unreadable_path = receipt["negative_path"]
    assert unreadable_path["case"] == "unreadable_intake_document"
    assert unreadable_path["run_id"] == "g03_acceptance_unreadable_01"
    assert unreadable_path["status"] == "blocked"
    assert unreadable_path["blocked_as_expected"] is True

    # Verify negative paths 2 & 3 (unclassifiable & ambiguous)
    additional_cases = {p["case"]: p for p in receipt["additional_negative_paths"]}
    assert "unclassifiable_intake_document" in additional_cases
    assert "ambiguous_intake_document" in additional_cases
    unclassifiable_path = additional_cases["unclassifiable_intake_document"]
    ambiguous_path = additional_cases["ambiguous_intake_document"]
    assert unclassifiable_path["status"] == "blocked"
    assert ambiguous_path["status"] == "blocked"

    # Verify handoff receipt
    assert len(receipt["handoff_receipts"]) == 1
    handoff_info = receipt["handoff_receipts"][0]
    assert handoff_info["producer"] == "smart_inbox"
    assert handoff_info["consumer"] == "folder_digest"
    assert handoff_info["status"] == "verified"
    handoff_file = bundle.root / handoff_info["artifact_path"]
    handoff = json.loads(handoff_file.read_text(encoding="utf-8"))
    assert handoff["format"] == "action-plan"
    assert handoff["producer_run_id"] == "g03_acceptance_positive_01"
    assert handoff["producer_workflow"] == "smart_inbox"

    # Verify SHA-256 for all artifacts
    assert all(
        hashlib.sha256((bundle.root / item["path"]).read_bytes()).hexdigest()
        == item["sha256"]
        for field in ("input_artifacts", "output_artifacts")
        for item in receipt[field]
    )

    # Verify run reports
    positive_report = json.loads(
        (bundle.root / receipt["run_report"]["path"]).read_text(encoding="utf-8")
    )
    unreadable_report = json.loads(
        (bundle.root / unreadable_path["run_report"]["path"]).read_text(encoding="utf-8")
    )
    unclassifiable_report = json.loads(
        (bundle.root / unclassifiable_path["run_report"]["path"]).read_text(encoding="utf-8")
    )
    ambiguous_report = json.loads(
        (bundle.root / ambiguous_path["run_report"]["path"]).read_text(encoding="utf-8")
    )

    assert positive_report["status"] == "executed"
    assert unreadable_report["status"] == "blocked"
    assert unreadable_report["errors"] == ["unreadable_input:01-scan-corrupt.txt"]
    assert unclassifiable_report["status"] == "blocked"
    assert unclassifiable_report["errors"] == ["unclassifiable_input:01-einkaufszettel.txt"]
    assert ambiguous_report["status"] == "blocked"
    assert ambiguous_report["errors"] == ["ambiguous_classification:01-mischdokument.txt"]

    # Verify index manifest artifact
    manifest_items = [
        item for item in receipt["output_artifacts"]
        if item["path"].endswith(".index-manifest.json")
    ]
    assert len(manifest_items) == 1
    manifest_data = json.loads(
        (bundle.root / manifest_items[0]["path"]).read_text(encoding="utf-8")
    )
    assert manifest_data["schema"] == "nemofold.index-manifest.v1"
    assert manifest_data["run_id"] == "g03_acceptance_positive_01"
    assert sum(1 for s in manifest_data["index_status"].values() if s == "indexed") == 2
    assert sum(1 for s in manifest_data["index_status"].values() if s == "updated") == 1
    assert manifest_data["pruned_source_ids"] == ["src_obsolete_draft"]

    # Verify needs-user-input artifacts for blocked runs
    input_prompts = [
        item for item in receipt["output_artifacts"]
        if item["path"].endswith(".needs-user-input.json")
    ]
    assert len(input_prompts) == 3


def test_g03_acceptance_bundle_cli_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["acceptance-g03", "--output", str(tmp_path / "cli-g03")])
    assert code == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["ok"] is True
    assert captured["gate_id"] == "G03"
    assert captured["verification"]["verified_evidence_gates"] == ["G03"]


def test_g03_acceptance_bundle_rejects_non_empty_root(tmp_path: Path) -> None:
    target = tmp_path / "non-empty-g03"
    target.mkdir(parents=True)
    (target / "existing.txt").write_text("blocked", encoding="utf-8")
    with pytest.raises(G03AcceptanceError, match="g03_evidence_root_not_empty"):
        run_g03_acceptance_bundle(target)
