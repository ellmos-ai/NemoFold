from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from nemofold.acceptance_gates import GateRegisterError, load_gate_register
from nemofold.cli import main
from nemofold.g02_acceptance import run_g02_acceptance_bundle


def test_g02_acceptance_bundle_verifies_positive_and_negative_runs(tmp_path: Path) -> None:
    bundle = run_g02_acceptance_bundle(
        tmp_path / "g02-evidence",
    )

    assert bundle.verification["verified_evidence_gates"] == ["G02"]
    assert bundle.verification["verified_done_gates"] == []
    assert bundle.verification["checked_file_count"] == 21
    register = json.loads(bundle.register_path.read_text(encoding="utf-8"))
    g02 = next(gate for gate in register["gates"] if gate["gate_id"] == "G02")
    assert g02["status"] == "partial"
    assert g02["evidence"]["test_nodes"] == []
    assert len(g02["evidence"]["run_receipts"]) == 1
    receipt = g02["evidence"]["run_receipts"][0]
    assert receipt["run_id"] == "g02_acceptance_positive_02"
    assert receipt["negative_path"]["run_id"] == "g02_acceptance_missing_page_01"
    authority_path = receipt["additional_negative_paths"][0]
    assert authority_path["case"] == "medical_diagnosis_requested"
    assert authority_path["run_id"] == "g02_acceptance_medical_authority_02"
    assert authority_path["status"] == "blocked"
    assert authority_path["blocked_as_expected"] is True
    handoff = json.loads(
        (bundle.root / receipt["handoff_receipts"][0]["artifact_path"]).read_text(
            encoding="utf-8"
        )
    )
    reviewed_text = "Befund: Schilddrüse Verlaufskontrolle empfohlen."
    assert handoff["source_scope"]["reviewed_pdf_page_count"] == 1
    assert handoff["consumer_source_scope"]["reviewed_pdf_page_count"] == 1
    assert handoff["verified_pdf_pages"][0]["reviewed_pages"][0][
        "text_sha256"
    ] == hashlib.sha256(reviewed_text.encode()).hexdigest()
    assert reviewed_text not in json.dumps(handoff, ensure_ascii=False)
    assert sum(
        item["path"].endswith(".json") and "/jobs/" in item["path"]
        for item in receipt["output_artifacts"]
    ) == 2

    positive_report = json.loads(
        (bundle.root / receipt["run_report"]["path"]).read_text(encoding="utf-8")
    )
    negative_report = json.loads(
        (bundle.root / receipt["negative_path"]["run_report"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    authority_report = json.loads(
        (
            bundle.root
            / authority_path["run_report"]["path"]
        ).read_text(encoding="utf-8")
    )
    assert positive_report["status"] == "executed"
    assert negative_report["status"] == "blocked"
    assert negative_report["errors"] == [
        "expected_pdf_page_gap:01-endokrinologie.pdf"
    ]
    assert authority_report["status"] == "blocked"
    assert authority_report["errors"] == ["medical_authority_denied:diagnosis"]
    assert authority_report["metadata"]["medical_authority"] == "denied"
    assert authority_report["metadata"]["needs_user_input"] is True
    assert Path(bundle.medical_authority_dossier_path).is_file()

    assert all(
        hashlib.sha256((bundle.root / item["path"]).read_bytes()).hexdigest()
        == item["sha256"]
        for field in ("input_artifacts", "output_artifacts")
        for item in receipt[field]
    )
    registry_path = next(
        bundle.root / item["path"]
        for item in receipt["output_artifacts"]
        if item["path"].endswith(".registry.json")
    )
    directory = json.loads(registry_path.read_text(encoding="utf-8"))
    assert directory["empty_cells"] == 0
    assert directory["filled_cells"] == 10
    assert {
        cell["value"]
        for row in directory["rows"]
        for cell in row["cells"]
        if cell["column"] == "Arzt"
    } == {"Dr. Mira Beispiel", "Dr. Noa Verlauf"}
    assert {
        cell["value"]
        for row in directory["rows"]
        for cell in row["cells"]
        if cell["column"] == "Kontakt"
    } == {
        "praxis-mira@example.invalid · +49 30 000001",
        "praxis-verlauf@example.invalid · +49 30 000002",
    }
    pdf_path = next(
        bundle.root / item["path"]
        for item in receipt["output_artifacts"]
        if item["path"].endswith("_synopsis.pdf")
    )
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(pdf_path).pages)
    assert "Schilddrüse unauffällig" in pdf_text
    assert "Schilddrüse vergrößert" in pdf_text
    assert "Schilddrüse Verlaufskontrolle empfohlen" in pdf_text
    assert "Knieverletzung" not in pdf_text
    assert "Leberwert auffällig" not in pdf_text

    bundle.positive_dossier_path.write_bytes(
        bundle.positive_dossier_path.read_bytes() + b"mutated"
    )
    with pytest.raises(GateRegisterError, match="evidence_sha256_mismatch:G02"):
        load_gate_register(bundle.register_path, evidence_root=bundle.root)


def test_g02_acceptance_cli_writes_verified_bundle(tmp_path: Path, capsys) -> None:
    output = tmp_path / "g02-cli-evidence"

    assert main(
        [
            "acceptance-g02",
            "--output",
            str(output),
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["gate_id"] == "G02"
    assert payload["verification"]["verified_evidence_gates"] == ["G02"]
    assert payload["verification"]["verified_done_gates"] == []
    assert Path(payload["register_path"]).is_file()

    assert main(
        [
            "acceptance-gates",
            "--register",
            payload["register_path"],
            "--evidence-root",
            str(output),
        ]
    ) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["summary"]["counts"] == {
        "done": 0,
        "not_supported": 2,
        "partial": 1,
        "planned": 15,
    }
    assert verified["gate_evidence_verification"]["verified_evidence_gates"] == ["G02"]
    assert verified["gate_evidence_verification"]["verified_done_gates"] == []

    assert main(["acceptance-gates", "--register", payload["register_path"]]) == 2
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["errors"] == ["gate_receipts_require_evidence_root:G02"]


def test_g02_acceptance_cli_refuses_a_nonempty_output_root(tmp_path: Path, capsys) -> None:
    output = tmp_path / "occupied"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("gehört dem Nutzer", encoding="utf-8")

    assert main(
        [
            "acceptance-g02",
            "--output",
            str(output),
        ]
    ) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["errors"] == [f"g02_evidence_root_not_empty:{output.resolve()}"]
    assert sentinel.read_text(encoding="utf-8") == "gehört dem Nutzer"


def test_g02_acceptance_bundle_uses_stable_voyage_identity(tmp_path: Path) -> None:
    first = run_g02_acceptance_bundle(tmp_path / "first")
    second = run_g02_acceptance_bundle(tmp_path / "second")

    first_register = json.loads(first.register_path.read_text(encoding="utf-8"))
    second_register = json.loads(second.register_path.read_text(encoding="utf-8"))
    first_receipt = next(
        gate for gate in first_register["gates"] if gate["gate_id"] == "G02"
    )["evidence"]["run_receipts"][0]
    second_receipt = next(
        gate for gate in second_register["gates"] if gate["gate_id"] == "G02"
    )["evidence"]["run_receipts"][0]

    assert [item["path"] for item in first_receipt["output_artifacts"]] == [
        item["path"] for item in second_receipt["output_artifacts"]
    ]
    assert json.loads(first.positive_dossier_path.read_text(encoding="utf-8"))[
        "voyage_id"
    ] == "voyage_g02_acceptance_positive"
    assert json.loads(first.negative_dossier_path.read_text(encoding="utf-8"))[
        "voyage_id"
    ] == "voyage_g02_acceptance_missing_page"
    assert json.loads(
        first.medical_authority_dossier_path.read_text(encoding="utf-8")
    )["voyage_id"] == "voyage_g02_acceptance_medical_authority"
    assert not (first.root / "run-reports" / "web-console" / "voyages").exists()
