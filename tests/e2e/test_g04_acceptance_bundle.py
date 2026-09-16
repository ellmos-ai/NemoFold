from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nemofold.cli import main
from nemofold.g04_acceptance import G04AcceptanceError, run_g04_acceptance_bundle


def test_g04_acceptance_bundle_verifies_positive_and_negative_runs(tmp_path: Path) -> None:
    bundle = run_g04_acceptance_bundle(
        tmp_path / "g04-evidence",
    )

    assert bundle.verification["verified_evidence_gates"] == ["G04"]
    assert bundle.verification["verified_done_gates"] == []
    register = json.loads(bundle.register_path.read_text(encoding="utf-8"))
    g04 = next(gate for gate in register["gates"] if gate["gate_id"] == "G04")
    assert g04["status"] == "partial"
    assert g04["evidence"]["test_nodes"] == []
    assert len(g04["evidence"]["run_receipts"]) == 1
    receipt = g04["evidence"]["run_receipts"][0]
    assert receipt["run_id"] == "g04_acceptance_positive_03"

    # Verify negative path 1 (missing coverage dates)
    missing_dates_path = receipt["negative_path"]
    assert missing_dates_path["case"] == "missing_contract_coverage_dates"
    assert missing_dates_path["run_id"] == "g04_acceptance_missing_dates_01"
    assert missing_dates_path["status"] == "blocked"
    assert missing_dates_path["blocked_as_expected"] is True

    # Verify negative paths 2 & 3 (missing required contract data & unauthorized broker advice)
    additional_cases = {p["case"]: p for p in receipt["additional_negative_paths"]}
    assert "missing_required_contract_data" in additional_cases
    assert "unauthorized_broker_advice" in additional_cases
    missing_data_path = additional_cases["missing_required_contract_data"]
    unauthorized_advice_path = additional_cases["unauthorized_broker_advice"]
    assert missing_data_path["status"] == "blocked"
    assert unauthorized_advice_path["status"] == "blocked"

    # Verify handoff receipt
    assert len(receipt["handoff_receipts"]) == 1
    handoff_info = receipt["handoff_receipts"][0]
    assert handoff_info["producer"] == "coverage_timeline"
    assert handoff_info["consumer"] == "folder_digest"
    assert handoff_info["status"] == "verified"
    handoff_file = bundle.root / handoff_info["artifact_path"]
    handoff = json.loads(handoff_file.read_text(encoding="utf-8"))
    assert handoff["format"] == "markdown"
    assert handoff["producer_run_id"] == "g04_acceptance_positive_02"
    assert handoff["producer_workflow"] == "coverage_timeline"

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
    unauthorized_advice_report = json.loads(
        (bundle.root / unauthorized_advice_path["run_report"]["path"]).read_text(encoding="utf-8")
    )

    assert positive_report["status"] == "executed"
    assert missing_dates_report["status"] == "blocked"
    assert missing_dates_report["errors"] == ["insufficient_coverage_intervals:0<1"]
    assert missing_data_report["status"] == "blocked"
    assert unauthorized_advice_report["status"] == "blocked"
    assert unauthorized_advice_report["errors"] == [
        "insurance_authority_denied:broker_recommendation"
    ]

    # Verify statutory disclaimer in consumer digest
    digest_items = [
        item for item in receipt["output_artifacts"]
        if item["path"].endswith(".digest.md")
    ]
    assert len(digest_items) == 1
    digest_text = (bundle.root / digest_items[0]["path"]).read_text(encoding="utf-8")
    assert "Nutzungsgrenze" in digest_text
    assert "§ 34d/e GewO" in digest_text


def test_g04_acceptance_bundle_cli_command(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli-evidence"
    code = main(["acceptance-g04", "--output", str(output_dir)])
    assert code == 0
    assert (output_dir / "gate-register.g04.json").is_file()
    assert (output_dir / "evidence" / "g04-handoff.json").is_file()


def test_g04_acceptance_bundle_rejects_non_empty_root(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "dirty"
    evidence_dir.mkdir()
    (evidence_dir / "stray.txt").write_text("not empty", encoding="utf-8")

    with pytest.raises(G04AcceptanceError, match="g04_evidence_root_not_empty"):
        run_g04_acceptance_bundle(evidence_dir)
