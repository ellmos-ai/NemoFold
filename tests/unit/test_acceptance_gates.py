from __future__ import annotations

import copy
import hashlib
import json

import pytest

from nemofold.acceptance_gates import (
    GateRegisterError,
    load_gate_register,
    summarize_gate_register,
    validate_gate_register,
    verify_ellmos_catalog,
)

EXPECTED_GATE_IDS = [f"G{number:02d}" for number in range(1, 19)]


def test_shipped_gate_register_is_complete_without_false_done_claims() -> None:
    register = load_gate_register()

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
            "partial": 1,
            "planned": 15,
        },
        "open_gates": EXPECTED_GATE_IDS,
    }


def test_done_gate_without_full_run_receipt_is_rejected() -> None:
    register = copy.deepcopy(load_gate_register())
    register["gates"][0]["status"] = "done"
    register["gates"][0]["evidence"]["run_receipts"] = []

    with pytest.raises(GateRegisterError, match="done_gate_requires_run_receipt:G01"):
        validate_gate_register(register)


def test_done_gate_rejects_placeholder_run_receipt_values() -> None:
    register = copy.deepcopy(load_gate_register())
    register["gates"][0]["status"] = "done"
    register["gates"][0]["evidence"]["run_receipts"] = [
        {
            field: "present"
            for field in register["completion_contract"]["required_run_receipt_fields"]
        }
    ]

    with pytest.raises(GateRegisterError, match="run_receipt_sha256_invalid:G01"):
        validate_gate_register(register)


def test_catalog_verification_blocks_hash_and_semantic_drift(tmp_path) -> None:
    register = copy.deepcopy(load_gate_register())
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
