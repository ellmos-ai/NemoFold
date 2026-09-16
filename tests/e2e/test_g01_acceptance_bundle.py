from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nemofold.cli import main
from nemofold.g01_acceptance import G01AcceptanceError, run_g01_acceptance_bundle


def test_g01_acceptance_bundle_verifies_positive_and_negative_runs(tmp_path: Path) -> None:
    bundle = run_g01_acceptance_bundle(
        tmp_path / "g01-evidence",
    )

    assert bundle.verification["verified_evidence_gates"] == ["G01"]
    assert bundle.verification["verified_done_gates"] == []
    assert bundle.verification["checked_file_count"] == 23

    register = json.loads(bundle.register_path.read_text(encoding="utf-8"))
    g01 = next(gate for gate in register["gates"] if gate["gate_id"] == "G01")
    assert g01["status"] == "partial"
    assert g01["evidence"]["test_nodes"] == []
    assert len(g01["evidence"]["run_receipts"]) == 1

    receipt = g01["evidence"]["run_receipts"][0]
    assert receipt["run_id"] == "g01_acceptance_positive_02"
    assert receipt["negative_path"]["run_id"] == "g01_acceptance_missing_tax_id_01"
    assert receipt["negative_path"]["case"] == "no_tax_id_found"
    assert receipt["negative_path"]["status"] == "blocked"
    assert receipt["negative_path"]["blocked_as_expected"] is True

    ambiguous_path = receipt["additional_negative_paths"][0]
    assert ambiguous_path["case"] == "ambiguous_tax_id_matches"
    assert ambiguous_path["run_id"] == "g01_acceptance_ambiguous_tax_id_01"
    assert ambiguous_path["status"] == "blocked"
    assert ambiguous_path["blocked_as_expected"] is True

    # Handoff artifact verification
    handoff_receipt = receipt["handoff_receipts"][0]
    assert handoff_receipt["producer"] == "corpus_query"
    assert handoff_receipt["consumer"] == "folder_digest"
    assert handoff_receipt["status"] == "verified"
    handoff_data = json.loads(
        (bundle.root / handoff_receipt["artifact_path"]).read_text(encoding="utf-8")
    )
    assert handoff_data["status"] == "verified"
    assert handoff_data["format"] == "markdown"
    assert handoff_data["producer_workflow"] == "corpus_query"

    # Verify all input and output artifacts exist with matching sha256
    assert all(
        hashlib.sha256((bundle.root / item["path"]).read_bytes()).hexdigest()
        == item["sha256"]
        for field in ("input_artifacts", "output_artifacts")
        for item in receipt[field]
    )

    # Verify result checks
    checks = {check["name"]: check for check in receipt["result_checks"]}
    assert set(checks) == {
        "document_found_with_tax_id",
        "exact_citation_and_line_locator",
        "verified_artifact_handoff",
    }
    assert all(check["passed"] is True for check in checks.values())

    # Dossiers exist
    assert Path(bundle.positive_dossier_path).is_file()
    assert Path(bundle.missing_dossier_path).is_file()
    assert Path(bundle.ambiguous_dossier_path).is_file()


def test_g01_acceptance_bundle_cli_command(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    output_dir = tmp_path / "g01-cli-out"
    code = main(["acceptance-g01", "--output", str(output_dir)])
    assert code == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["gate_id"] == "G01"
    assert payload["verification"]["verified_evidence_gates"] == ["G01"]
    assert payload["verification"]["checked_file_count"] == 23


def test_g01_acceptance_bundle_fails_on_non_empty_dir(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "non-empty-dir"
    evidence_dir.mkdir()
    (evidence_dir / "stray.txt").write_text("not empty", encoding="utf-8")

    with pytest.raises(G01AcceptanceError, match="g01_evidence_root_not_empty"):
        run_g01_acceptance_bundle(evidence_dir)
