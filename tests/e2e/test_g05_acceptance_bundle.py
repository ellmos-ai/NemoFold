from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nemofold.cli import main
from nemofold.g05_acceptance import G05AcceptanceError, run_g05_acceptance_bundle


def test_g05_acceptance_bundle_verifies_positive_and_negative_runs(tmp_path: Path) -> None:
    bundle = run_g05_acceptance_bundle(
        tmp_path / "g05-evidence",
    )

    assert bundle.verification["verified_evidence_gates"] == ["G05"]
    assert bundle.verification["verified_done_gates"] == []
    register = json.loads(bundle.register_path.read_text(encoding="utf-8"))
    g05 = next(gate for gate in register["gates"] if gate["gate_id"] == "G05")
    assert g05["status"] == "partial"
    assert g05["evidence"]["test_nodes"] == []
    assert len(g05["evidence"]["run_receipts"]) == 1
    receipt = g05["evidence"]["run_receipts"][0]

    # Verify negative path 1 (missing cost due dates)
    missing_dates_path = receipt["negative_path"]
    assert missing_dates_path["case"] == "missing_cost_due_dates"
    assert missing_dates_path["status"] == "blocked"
    assert missing_dates_path["blocked_as_expected"] is True

    # Verify additional negative paths (missing required cost column & insufficient items floor)
    additional_cases = {p["case"]: p for p in receipt["additional_negative_paths"]}
    assert "missing_required_cost_amount_column" in additional_cases
    assert "insufficient_cost_items_floor" in additional_cases
    missing_data_path = additional_cases["missing_required_cost_amount_column"]
    insufficient_items_path = additional_cases["insufficient_cost_items_floor"]
    assert missing_data_path["status"] == "blocked"
    assert insufficient_items_path["status"] == "blocked"

    # Verify handoff receipt
    assert len(receipt["handoff_receipts"]) == 1
    handoff_info = receipt["handoff_receipts"][0]
    assert handoff_info["producer"] == "cost_timeline"
    assert handoff_info["consumer"] == "folder_digest"
    assert handoff_info["status"] == "verified"
    handoff_file = bundle.root / handoff_info["artifact_path"]
    handoff = json.loads(handoff_file.read_text(encoding="utf-8"))
    assert handoff["format"] == "markdown"
    assert handoff["producer_workflow"] == "cost_timeline"

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
    missing_dates_report = json.loads(
        (bundle.root / missing_dates_path["run_report"]["path"]).read_text(encoding="utf-8")
    )
    missing_data_report = json.loads(
        (bundle.root / missing_data_path["run_report"]["path"]).read_text(encoding="utf-8")
    )
    insufficient_items_report = json.loads(
        (bundle.root / insufficient_items_path["run_report"]["path"]).read_text(encoding="utf-8")
    )

    assert positive_report["status"] == "executed"
    assert missing_dates_report["status"] == "blocked"
    assert missing_data_report["status"] == "blocked"
    assert insufficient_items_report["status"] == "blocked"


def test_g05_acceptance_bundle_cli_command(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli-evidence"
    code = main(["acceptance-g05", "--output", str(output_dir)])
    assert code == 0
    assert (output_dir / "gate-register.g05.json").is_file()
    assert (output_dir / "evidence" / "g05-handoff.json").is_file()


def test_g05_acceptance_bundle_rejects_non_empty_root(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "dirty"
    evidence_dir.mkdir()
    (evidence_dir / "stray.txt").write_text("not empty", encoding="utf-8")

    with pytest.raises(G05AcceptanceError, match="g05_evidence_root_not_empty"):
        run_g05_acceptance_bundle(evidence_dir)
