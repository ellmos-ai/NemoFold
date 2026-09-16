"""Tests for Gate G16 acceptance bundle and verification CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.cli import main
from nemofold.g16_acceptance import G16AcceptanceError, run_g16_acceptance_bundle


def test_g16_acceptance_bundle_verifies_positive_and_negative_runs(tmp_path: Path) -> None:
    bundle = run_g16_acceptance_bundle(
        tmp_path / "g16-evidence",
    )

    assert bundle.register_path.is_file()
    assert bundle.positive_dossier_path.is_file()
    assert bundle.omitted_items_report_path.is_file()
    assert bundle.undeclared_code_report_path.is_file()
    assert bundle.invalid_scheme_report_path.is_file()
    assert bundle.scale_load_report_path.is_file()

    assert bundle.scale_benchmark["item_count"] == 1000
    assert bundle.scale_benchmark["elapsed_seconds"] > 0
    assert bundle.scale_benchmark["agreed_items"] > 0

    assert bundle.verification["verified_evidence_gates"] == ["G16"]
    assert bundle.verification["verified_done_gates"] == []
    register = json.loads(bundle.register_path.read_text(encoding="utf-8"))
    gate = next(g for g in register["gates"] if g["gate_id"] == "G16")
    assert gate["status"] == "partial"
    assert gate["evidence"]["test_nodes"] == []
    assert len(gate["evidence"]["run_receipts"]) == 1

    receipt = gate["evidence"]["run_receipts"][0]
    assert receipt["run_id"] == "vy_g16_pos_run_03"
    assert receipt["handoff_receipts"][0]["producer"] == "document_registry"
    assert receipt["handoff_receipts"][0]["consumer"] == "rater_race"
    assert receipt["handoff_receipts"][1]["producer"] == "rater_race"
    assert receipt["handoff_receipts"][1]["consumer"] == "folder_digest"

    expected_neg_case = "omitted_items_in_coding_sheet_blocked"
    assert receipt["negative_path"]["case"] == expected_neg_case
    assert receipt["negative_path"]["status"] == "blocked"
    assert receipt["negative_path"]["blocked_as_expected"] is True
    assert len(receipt["additional_negative_paths"]) == 2

    manifest_path = bundle.root / "evidence" / "g16-evidence-dossier.json"
    assert manifest_path.is_file()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["run_id"] == "vy_g16_pos_run_03"

    markdown_dossier = manifest_path.with_suffix(".md")
    assert markdown_dossier.is_file()
    markdown_text = markdown_dossier.read_text(encoding="utf-8")
    assert "# G16 Acceptance Dossier" in markdown_text
    assert "Scale Load Benchmark (D-030 1,000 Questionnaires)" in markdown_text


def test_g16_acceptance_bundle_rejects_non_empty_root(tmp_path: Path) -> None:
    non_empty = tmp_path / "occupied"
    non_empty.mkdir(parents=True)
    (non_empty / "stray.txt").write_text("blocked", encoding="utf-8")

    with pytest.raises(G16AcceptanceError, match="g16_evidence_root_not_empty"):
        run_g16_acceptance_bundle(non_empty)


def test_g16_acceptance_bundle_cli_command(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli-evidence"
    code = main(["acceptance-g16", "--output", str(output_dir)])
    assert code == 0

    evidence_json = output_dir / "evidence" / "g16-evidence-dossier.json"
    assert evidence_json.is_file()
    payload = json.loads(evidence_json.read_text(encoding="utf-8"))
    assert payload["run_id"] == "vy_g16_pos_run_03"
