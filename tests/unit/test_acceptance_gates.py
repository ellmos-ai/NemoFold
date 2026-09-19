from __future__ import annotations

import copy
import hashlib
import json
import os

import pytest

from nemofold.acceptance_gates import (
    GateRegisterError,
    load_gate_register,
    load_gate_register_template,
    summarize_gate_register,
    validate_gate_register,
    verify_ellmos_catalog,
    verify_gate_evidence,
)

EXPECTED_GATE_IDS = [f"G{number:02d}" for number in range(1, 19)]


def _manifest_sha256(artifacts: list[dict[str, str]]) -> str:
    canonical = json.dumps(
        artifacts,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _dummy_test_node() -> dict[str, str]:
    return {
        "node": "tests/e2e/test_g01.py::test_g01",
        "file_sha256": hashlib.sha256(b"test node").hexdigest(),
    }


def _done_register_with_files(root) -> tuple[dict, dict[str, object]]:
    files = {
        "inputs/source.txt": b"Steuernummer: 12/345/67890\n",
        "outputs/result.json": b'{"document":"steuerbescheid.pdf","line":1}',
        "tests/e2e/test_g01.py": b"def test_g01():\n    assert True\n",
        "evidence/g01-handoff.json": b'{"schema":"nemofold.handoff.v1"}',
        "evidence/g01-run-report.json": (
            b'{"run_id":"g01-20260916-verified","status":"executed"}'
        ),
        "evidence/g01-negative-run-report.json": (
            b'{"run_id":"g01-20260916-blocked","status":"blocked"}'
        ),
    }
    paths = {}
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        paths[relative] = path

    register = copy.deepcopy(load_gate_register_template())
    input_artifacts = [
        {
            "path": "inputs/source.txt",
            "sha256": hashlib.sha256(files["inputs/source.txt"]).hexdigest(),
        }
    ]
    output_artifacts = [
        {
            "path": "outputs/result.json",
            "sha256": hashlib.sha256(files["outputs/result.json"]).hexdigest(),
        }
    ]
    gate = register["gates"][0]
    gate["status"] = "done"
    gate["evidence"]["test_nodes"] = [
        {
            "node": "tests/e2e/test_g01.py::test_g01",
            "file_sha256": hashlib.sha256(files["tests/e2e/test_g01.py"]).hexdigest(),
        }
    ]
    gate["evidence"]["run_receipts"] = [
        {
            "run_id": "g01-20260916-verified",
            "input_sha256": _manifest_sha256(input_artifacts),
            "output_sha256": _manifest_sha256(output_artifacts),
            "input_artifacts": input_artifacts,
            "output_artifacts": output_artifacts,
            "handoff_receipts": [
                {
                    "producer": "inventory",
                    "consumer": "document_search",
                    "artifact_path": "evidence/g01-handoff.json",
                    "artifact_sha256": hashlib.sha256(
                        files["evidence/g01-handoff.json"]
                    ).hexdigest(),
                    "status": "verified",
                    "evidence": "Übergabedatei vorhanden und hashgebunden.",
                }
            ],
            "run_report": {
                "path": "evidence/g01-run-report.json",
                "sha256": hashlib.sha256(
                    files["evidence/g01-run-report.json"]
                ).hexdigest(),
                "status": "executed",
                "verified": True,
            },
            "result_checks": [
                {
                    "name": "source_locator_matches",
                    "passed": True,
                    "evidence": "Treffer und Fundstelle stimmen überein.",
                }
            ],
            "negative_path": {
                "case": "ambiguous_document",
                "run_id": "g01-20260916-blocked",
                "status": "blocked",
                "blocked_as_expected": True,
                "evidence": "Mehrdeutiger Treffer wurde blockiert.",
                "run_report": {
                    "path": "evidence/g01-negative-run-report.json",
                    "sha256": hashlib.sha256(
                        files["evidence/g01-negative-run-report.json"]
                    ).hexdigest(),
                },
            },
        }
    ]
    return register, paths


def test_shipped_gate_register_is_complete_without_false_done_claims() -> None:
    # The shipped register claims done gates, and a done claim cannot be read
    # without the files that back it.
    with pytest.raises(GateRegisterError, match="done_gate_requires_evidence_root"):
        load_gate_register()

    register = load_gate_register_template()

    assert [gate["gate_id"] for gate in register["gates"]] == EXPECTED_GATE_IDS
    assert {item["id"] for item in register["source_catalog"]["selected_usecases"]} == {
        1,
        2,
        3,
        4,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        16,
        23,
        25,
        32,
        37,
        38,
        39,
        40,
        41,
        42,
        44,
        45,
        47,
        49,
    }
    assert summarize_gate_register(register) == {
        "complete": False,
        "counts": {
            "done": 0,
            "not_supported": 2,
            "partial": 0,
            "planned": 16,
        },
        "open_gates": EXPECTED_GATE_IDS,
    }


def test_done_gate_without_full_run_receipt_is_rejected() -> None:
    register = copy.deepcopy(load_gate_register_template())
    register["gates"][0]["status"] = "done"
    register["gates"][0]["evidence"]["test_nodes"] = [_dummy_test_node()]
    register["gates"][0]["evidence"]["run_receipts"] = []

    with pytest.raises(GateRegisterError, match="done_gate_requires_run_receipt:G01"):
        validate_gate_register(register)


def test_done_gate_rejects_placeholder_run_receipt_values() -> None:
    register = copy.deepcopy(load_gate_register_template())
    register["gates"][0]["status"] = "done"
    register["gates"][0]["evidence"]["test_nodes"] = [_dummy_test_node()]
    register["gates"][0]["evidence"]["run_receipts"] = [
        {
            field: "present"
            for field in register["completion_contract"]["required_run_receipt_fields"]
        }
    ]
    register["gates"][0]["evidence"]["run_receipts"][0]["run_id"] = "g01-run-001"

    with pytest.raises(GateRegisterError, match="run_receipt_sha256_invalid:G01"):
        validate_gate_register(register)


def test_done_gate_rejects_semantically_empty_structured_placeholders() -> None:
    register = copy.deepcopy(load_gate_register_template())
    gate = register["gates"][0]
    gate["status"] = "done"
    gate["evidence"]["test_nodes"] = [_dummy_test_node()]
    gate["evidence"]["run_receipts"] = [
        {
            "run_id": "g01-run-001",
            "input_sha256": "0" * 64,
            "output_sha256": "0" * 64,
            "input_artifacts": ["present"],
            "output_artifacts": ["present"],
            "handoff_receipts": ["present"],
            "run_report": "present",
            "result_checks": ["present"],
            "negative_path": {"present": True},
        }
    ]

    with pytest.raises(GateRegisterError, match="run_receipt_sha256_placeholder:G01"):
        validate_gate_register(register)


def test_done_gate_requires_an_evidence_root_for_file_verification(tmp_path) -> None:
    register, _ = _done_register_with_files(tmp_path)

    with pytest.raises(GateRegisterError, match="done_gate_requires_evidence_root:G01"):
        validate_gate_register(register)


def test_done_gate_verifies_referenced_files_and_blocks_mutation(tmp_path) -> None:
    register, paths = _done_register_with_files(tmp_path)

    validated = validate_gate_register(register, evidence_root=tmp_path)
    verification = verify_gate_evidence(validated, tmp_path)

    assert summarize_gate_register(validated, evidence_root=tmp_path)["counts"]["done"] == 1
    assert verification == {
        "evidence_root": str(tmp_path.resolve()),
        "verified_evidence_gates": ["G01"],
        "verified_done_gates": ["G01"],
        "checked_file_count": 6,
        "checked_files": [
            "evidence/g01-handoff.json",
            "evidence/g01-negative-run-report.json",
            "evidence/g01-run-report.json",
            "inputs/source.txt",
            "outputs/result.json",
            "tests/e2e/test_g01.py",
        ],
    }

    paths["evidence/g01-handoff.json"].write_bytes(b'{"mutated":true}')
    with pytest.raises(GateRegisterError, match="evidence_sha256_mismatch:G01"):
        validate_gate_register(register, evidence_root=tmp_path)


def test_declared_additional_negative_paths_are_hash_and_run_bound(tmp_path) -> None:
    """Catches a second full-usecase blocker being declared but never verified."""
    register, _ = _done_register_with_files(tmp_path)
    path = tmp_path / "evidence" / "g01-medical-authority-run-report.json"
    raw = b'{"run_id":"g01-20260916-medical-blocked","status":"blocked"}'
    path.write_bytes(raw)
    receipt = register["gates"][0]["evidence"]["run_receipts"][0]
    receipt["additional_negative_paths"] = [
        {
            "case": "medical_diagnosis_requested",
            "run_id": "g01-20260916-medical-blocked",
            "status": "blocked",
            "blocked_as_expected": True,
            "evidence": "Diagnosewunsch wurde ohne klinische Autorität blockiert.",
            "run_report": {
                "path": "evidence/g01-medical-authority-run-report.json",
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
        }
    ]

    validated = validate_gate_register(register, evidence_root=tmp_path)
    verification = verify_gate_evidence(validated, tmp_path)

    assert "evidence/g01-medical-authority-run-report.json" in verification[
        "checked_files"
    ]
    assert verification["checked_file_count"] == 7

    path.write_bytes(b'{"run_id":"forged","status":"blocked"}')
    with pytest.raises(GateRegisterError, match="evidence_sha256_mismatch:G01"):
        validate_gate_register(register, evidence_root=tmp_path)

    receipt["additional_negative_paths"][0]["run_report"]["sha256"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    with pytest.raises(
        GateRegisterError,
        match="additional_negative_path_run_id_mismatch:G01",
    ):
        validate_gate_register(register, evidence_root=tmp_path)


def test_additional_negative_paths_require_unique_run_ids(tmp_path) -> None:
    register, _ = _done_register_with_files(tmp_path)
    receipt = register["gates"][0]["evidence"]["run_receipts"][0]
    duplicate_run = dict(receipt["negative_path"])
    duplicate_run["case"] = "different_negative_case"
    receipt["additional_negative_paths"] = [duplicate_run]

    with pytest.raises(GateRegisterError, match="duplicate_negative_run_id:G01"):
        validate_gate_register(register)


def test_additional_negative_paths_require_unique_case_roles(tmp_path) -> None:
    register, _ = _done_register_with_files(tmp_path)
    receipt = register["gates"][0]["evidence"]["run_receipts"][0]
    primary = receipt["negative_path"]
    receipt["additional_negative_paths"] = [
        {
            **primary,
            "run_id": "g01-second-negative-run",
            "run_report": {
                "path": "evidence/g01-second-negative-run-report.json",
                "sha256": hashlib.sha256(b"second negative report").hexdigest(),
            },
        }
    ]

    with pytest.raises(GateRegisterError, match="duplicate_negative_case:G01"):
        validate_gate_register(register)


def test_done_gate_requires_input_and_output_artifact_manifests(tmp_path) -> None:
    register, _ = _done_register_with_files(tmp_path)
    del register["gates"][0]["evidence"]["run_receipts"][0]["input_artifacts"]

    with pytest.raises(GateRegisterError, match="run_receipt_fields_missing:G01:input_artifacts"):
        validate_gate_register(register, evidence_root=tmp_path)


def test_done_gate_blocks_input_bytes_and_manifest_hash_drift(tmp_path) -> None:
    register, paths = _done_register_with_files(tmp_path)
    paths["inputs/source.txt"].write_bytes(b"manipulated input")

    with pytest.raises(
        GateRegisterError,
        match="evidence_sha256_mismatch:G01:input_artifact:inputs/source.txt",
    ):
        validate_gate_register(register, evidence_root=tmp_path)

    register, _ = _done_register_with_files(tmp_path)
    register["gates"][0]["evidence"]["run_receipts"][0]["input_sha256"] = hashlib.sha256(
        b"wrong manifest"
    ).hexdigest()
    with pytest.raises(GateRegisterError, match="input_manifest_sha256_mismatch:G01"):
        validate_gate_register(register, evidence_root=tmp_path)


def test_done_gate_blocks_test_node_mutation(tmp_path) -> None:
    register, paths = _done_register_with_files(tmp_path)
    paths["tests/e2e/test_g01.py"].write_bytes(b"arbitrary bytes")

    with pytest.raises(GateRegisterError, match="evidence_sha256_mismatch:G01:test_node"):
        validate_gate_register(register, evidence_root=tmp_path)


def test_done_gate_rejects_rehashed_file_without_declared_test_node(tmp_path) -> None:
    register, paths = _done_register_with_files(tmp_path)
    replacement = b"def test_other():\n    assert True\n"
    paths["tests/e2e/test_g01.py"].write_bytes(replacement)
    register["gates"][0]["evidence"]["test_nodes"][0]["file_sha256"] = hashlib.sha256(
        replacement
    ).hexdigest()

    with pytest.raises(GateRegisterError, match="test_node_not_found:G01"):
        validate_gate_register(register, evidence_root=tmp_path)


def test_done_gate_blocks_normalized_duplicate_artifact_paths(tmp_path) -> None:
    register, _ = _done_register_with_files(tmp_path)
    receipt = register["gates"][0]["evidence"]["run_receipts"][0]
    receipt["input_artifacts"].append(
        {
            "path": "inputs/./source.txt",
            "sha256": receipt["input_artifacts"][0]["sha256"],
        }
    )
    receipt["input_sha256"] = _manifest_sha256(receipt["input_artifacts"])

    with pytest.raises(GateRegisterError, match="duplicate_input_artifact:G01"):
        validate_gate_register(register, evidence_root=tmp_path)


def test_done_gate_blocks_cross_role_and_handoff_path_duplicates(tmp_path) -> None:
    register, _ = _done_register_with_files(tmp_path)
    receipt = register["gates"][0]["evidence"]["run_receipts"][0]
    receipt["output_artifacts"] = [copy.deepcopy(receipt["input_artifacts"][0])]
    receipt["output_sha256"] = _manifest_sha256(receipt["output_artifacts"])

    with pytest.raises(GateRegisterError, match="artifact_used_as_input_and_output:G01"):
        validate_gate_register(register, evidence_root=tmp_path)

    register, _ = _done_register_with_files(tmp_path)
    receipt = register["gates"][0]["evidence"]["run_receipts"][0]
    duplicate = copy.deepcopy(receipt["handoff_receipts"][0])
    duplicate["artifact_path"] = "evidence/./g01-handoff.json"
    receipt["handoff_receipts"].append(duplicate)
    with pytest.raises(GateRegisterError, match="duplicate_handoff_receipt:G01"):
        validate_gate_register(register, evidence_root=tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows path identity is case-insensitive")
def test_done_gate_blocks_case_alias_artifact_duplicates_on_windows(tmp_path) -> None:
    register, _ = _done_register_with_files(tmp_path)
    receipt = register["gates"][0]["evidence"]["run_receipts"][0]
    duplicate = copy.deepcopy(receipt["input_artifacts"][0])
    duplicate["path"] = "INPUTS/SOURCE.TXT"
    receipt["input_artifacts"].append(duplicate)
    receipt["input_sha256"] = _manifest_sha256(receipt["input_artifacts"])

    with pytest.raises(GateRegisterError, match="duplicate_input_artifact:G01"):
        validate_gate_register(register, evidence_root=tmp_path)


def test_done_gate_blocks_artifact_reuse_as_handoff(tmp_path) -> None:
    register, _ = _done_register_with_files(tmp_path)
    receipt = register["gates"][0]["evidence"]["run_receipts"][0]
    receipt["handoff_receipts"][0]["artifact_path"] = receipt["input_artifacts"][0][
        "path"
    ]
    receipt["handoff_receipts"][0]["artifact_sha256"] = receipt["input_artifacts"][0][
        "sha256"
    ]

    with pytest.raises(GateRegisterError, match="evidence_path_role_conflict:G01"):
        validate_gate_register(register, evidence_root=tmp_path)


def test_done_gate_requires_distinct_positive_and_negative_run_ids(tmp_path) -> None:
    register, paths = _done_register_with_files(tmp_path)
    receipt = register["gates"][0]["evidence"]["run_receipts"][0]
    receipt["negative_path"]["run_id"] = receipt["run_id"]
    report = b'{"run_id":"g01-20260916-verified","status":"blocked"}'
    paths["evidence/g01-negative-run-report.json"].write_bytes(report)
    receipt["negative_path"]["run_report"]["sha256"] = hashlib.sha256(report).hexdigest()

    with pytest.raises(GateRegisterError, match="positive_and_negative_run_id_same:G01"):
        validate_gate_register(register, evidence_root=tmp_path)


def test_done_gate_blocks_placeholder_file_bytes(tmp_path) -> None:
    register, paths = _done_register_with_files(tmp_path)
    receipt = register["gates"][0]["evidence"]["run_receipts"][0]
    paths["inputs/source.txt"].write_bytes(b"present")
    receipt["input_artifacts"][0]["sha256"] = hashlib.sha256(b"present").hexdigest()
    receipt["input_sha256"] = _manifest_sha256(receipt["input_artifacts"])

    with pytest.raises(GateRegisterError, match="evidence_file_placeholder:G01:input_artifact"):
        validate_gate_register(register, evidence_root=tmp_path)


def test_done_gate_blocks_placeholder_evidence_text(tmp_path) -> None:
    register, _ = _done_register_with_files(tmp_path)
    register["gates"][0]["evidence"]["run_receipts"][0]["handoff_receipts"][0][
        "evidence"
    ] = "present"

    with pytest.raises(GateRegisterError, match="handoff_receipt_evidence_placeholder:G01"):
        validate_gate_register(register, evidence_root=tmp_path)


def test_done_gate_reads_run_report_identity_and_status(tmp_path) -> None:
    register, paths = _done_register_with_files(tmp_path)
    receipt = register["gates"][0]["evidence"]["run_receipts"][0]
    wrong_report = b'{"run_id":"different-run","status":"executed"}'
    paths["evidence/g01-run-report.json"].write_bytes(wrong_report)
    receipt["run_report"]["sha256"] = hashlib.sha256(wrong_report).hexdigest()

    with pytest.raises(GateRegisterError, match="run_report_run_id_mismatch:G01"):
        validate_gate_register(register, evidence_root=tmp_path)


def test_done_gate_blocks_evidence_path_escape(tmp_path) -> None:
    register, _ = _done_register_with_files(tmp_path)
    register["gates"][0]["evidence"]["run_receipts"][0]["handoff_receipts"][0][
        "artifact_path"
    ] = "../outside.json"

    with pytest.raises(GateRegisterError, match="evidence_path_traversal:G01"):
        validate_gate_register(register, evidence_root=tmp_path)


def test_catalog_verification_blocks_hash_and_semantic_drift(tmp_path) -> None:
    register = copy.deepcopy(load_gate_register_template())
    catalog_path = tmp_path / "usecases.json"
    catalog = {"usecases": register["source_catalog"]["selected_usecases"]}
    raw = json.dumps(catalog, ensure_ascii=False).encode("utf-8")
    catalog_path.write_bytes(raw)
    register["source_catalog"]["sha256"] = hashlib.sha256(raw).hexdigest()

    verification = verify_ellmos_catalog(register, catalog_path)
    assert verification == {
        "catalog_path": str(catalog_path.resolve()),
        "catalog_verified": True,
        "selected_usecase_count": 26,
        "sha256": register["source_catalog"]["sha256"],
    }

    changed = copy.deepcopy(catalog)
    changed["usecases"][0]["title"] = "Geänderter Titel"
    changed_raw = json.dumps(changed, ensure_ascii=False).encode("utf-8")
    catalog_path.write_bytes(changed_raw)

    with pytest.raises(GateRegisterError, match="ellmos_catalog_sha256_mismatch"):
        verify_ellmos_catalog(register, catalog_path)

    register["source_catalog"]["sha256"] = hashlib.sha256(changed_raw).hexdigest()
    with pytest.raises(GateRegisterError, match="ellmos_usecase_mismatch:1"):
        verify_ellmos_catalog(register, catalog_path)
