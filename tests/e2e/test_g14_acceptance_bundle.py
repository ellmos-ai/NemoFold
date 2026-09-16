"""Tests for Gate G14 acceptance bundle and verification CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.cli import main
from nemofold.g14_acceptance import G14AcceptanceError, run_g14_acceptance_bundle


def test_g14_acceptance_bundle_verifies_positive_and_negative_runs(tmp_path: Path) -> None:
    bundle = run_g14_acceptance_bundle(
        tmp_path / "g14-evidence",
    )

    assert bundle.register_path.is_file()
    assert bundle.positive_dossier_path.is_file()
    assert bundle.sparse_dossier_path.is_file()
    assert bundle.unapproved_dossier_path.is_file()
    assert bundle.sensitive_dossier_path.is_file()
    assert bundle.missing_subject_dossier_path.is_file()

    assert bundle.verification["verified_evidence_gates"] == ["G14"]
    assert bundle.verification["verified_done_gates"] == []
    register = json.loads(bundle.register_path.read_text(encoding="utf-8"))
    gate = next(g for g in register["gates"] if g["gate_id"] == "G14")
    assert gate["status"] == "partial"
    assert gate["evidence"]["test_nodes"] == []
    assert len(gate["evidence"]["run_receipts"]) == 1

    receipt = gate["evidence"]["run_receipts"][0]
    assert receipt["run_id"] == "vy_g14_pos_03"
    assert receipt["handoff_receipts"][0]["producer"] == "web_research"
    assert receipt["handoff_receipts"][0]["consumer"] == "briefing"
    assert receipt["handoff_receipts"][1]["producer"] == "briefing"
    assert receipt["handoff_receipts"][1]["consumer"] == "document_qa"

    expected_neg_case = "unapproved_web_search_blocked"
    assert receipt["negative_path"]["case"] == expected_neg_case
    assert receipt["negative_path"]["status"] == "blocked"
    assert receipt["negative_path"]["blocked_as_expected"] is True
    assert len(receipt["additional_negative_paths"]) == 3

    manifest_path = bundle.root / "evidence" / "g14-evidence-dossier.json"
    assert manifest_path.is_file()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["run_id"] == "vy_g14_pos_03"

    markdown_dossier = manifest_path.with_suffix(".md")
    assert markdown_dossier.is_file()
    markdown_text = markdown_dossier.read_text(encoding="utf-8")
    assert "# G14 Acceptance Dossier" in markdown_text
    assert "separation_of_facts_and_inferences_verified" in markdown_text


def test_g14_acceptance_bundle_rejects_non_empty_root(tmp_path: Path) -> None:
    non_empty = tmp_path / "occupied"
    non_empty.mkdir(parents=True)
    (non_empty / "stray.txt").write_text("blocked", encoding="utf-8")

    with pytest.raises(G14AcceptanceError, match="g14_evidence_root_not_empty"):
        run_g14_acceptance_bundle(non_empty)


def test_g14_acceptance_bundle_cli_command(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli-evidence"
    code = main(["acceptance-g14", "--output", str(output_dir)])
    assert code == 0

    evidence_json = output_dir / "evidence" / "g14-evidence-dossier.json"
    assert evidence_json.is_file()
    payload = json.loads(evidence_json.read_text(encoding="utf-8"))
    assert payload["run_id"] == "vy_g14_pos_03"
