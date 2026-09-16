from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from importlib.resources import files
from pathlib import Path
from typing import Any

EXPECTED_GATE_IDS = tuple(f"G{number:02d}" for number in range(1, 19))
ALLOWED_STATUSES = frozenset({"planned", "partial", "not_supported", "done"})
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class GateRegisterError(ValueError):
    """Raised when the acceptance register or its provenance is invalid."""


def load_gate_register(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        resource = files("nemofold").joinpath("data", "nf_fin_gates.json")
        raw = resource.read_text(encoding="utf-8")
    else:
        raw = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateRegisterError(f"invalid_gate_register_json:{exc.msg}") from exc
    return validate_gate_register(payload)


def validate_gate_register(payload: object) -> dict[str, Any]:
    register = _mapping(payload, "gate_register_must_be_object")
    if register.get("schema") != "nemofold.acceptance-gates.v1":
        raise GateRegisterError("unsupported_gate_register_schema")

    source = _mapping(register.get("source_catalog"), "source_catalog_must_be_object")
    source_sha = source.get("sha256")
    if not isinstance(source_sha, str) or SHA256_PATTERN.fullmatch(source_sha) is None:
        raise GateRegisterError("source_catalog_sha256_invalid")
    selected = source.get("selected_usecases")
    if not isinstance(selected, list) or not selected:
        raise GateRegisterError("selected_usecases_must_be_nonempty_list")
    selected_by_id: dict[int, dict[str, Any]] = {}
    for item in selected:
        entry = _mapping(item, "selected_usecase_must_be_object")
        usecase_id = entry.get("id")
        if not isinstance(usecase_id, int) or usecase_id <= 0:
            raise GateRegisterError("selected_usecase_id_invalid")
        if usecase_id in selected_by_id:
            raise GateRegisterError(f"duplicate_selected_usecase:{usecase_id}")
        _nonempty_string(entry.get("title"), f"selected_usecase_title_missing:{usecase_id}")
        _nonempty_string(
            entry.get("description"), f"selected_usecase_description_missing:{usecase_id}"
        )
        selected_by_id[usecase_id] = entry

    contract = _mapping(
        register.get("completion_contract"), "completion_contract_must_be_object"
    )
    receipt_fields = contract.get("required_run_receipt_fields")
    if not isinstance(receipt_fields, list) or not receipt_fields:
        raise GateRegisterError("required_run_receipt_fields_missing")
    if not all(isinstance(field, str) and field for field in receipt_fields):
        raise GateRegisterError("required_run_receipt_field_invalid")

    gates = register.get("gates")
    if not isinstance(gates, list):
        raise GateRegisterError("gates_must_be_list")
    gate_ids = [gate.get("gate_id") if isinstance(gate, dict) else None for gate in gates]
    if gate_ids != list(EXPECTED_GATE_IDS):
        raise GateRegisterError("gate_ids_must_be_exactly_G01_through_G18")

    referenced_usecase_ids: set[int] = set()
    for raw_gate in gates:
        gate = _mapping(raw_gate, "gate_must_be_object")
        gate_id = str(gate["gate_id"])
        status = gate.get("status")
        if status not in ALLOWED_STATUSES:
            raise GateRegisterError(f"gate_status_invalid:{gate_id}")
        usecase_ids = gate.get("ellmos_usecase_ids")
        external_ids = gate.get("external_requirement_ids")
        if not isinstance(usecase_ids, list) or not all(
            isinstance(item, int) and item > 0 for item in usecase_ids
        ):
            raise GateRegisterError(f"ellmos_usecase_ids_invalid:{gate_id}")
        if not isinstance(external_ids, list) or not all(
            isinstance(item, str) and item for item in external_ids
        ):
            raise GateRegisterError(f"external_requirement_ids_invalid:{gate_id}")
        if not usecase_ids and not external_ids:
            raise GateRegisterError(f"gate_requires_source_mapping:{gate_id}")
        for usecase_id in usecase_ids:
            if usecase_id not in selected_by_id:
                raise GateRegisterError(f"unknown_ellmos_usecase:{gate_id}:{usecase_id}")
            referenced_usecase_ids.add(usecase_id)
        for field in ("application_chain", "expected_outcomes", "negative_cases"):
            values = gate.get(field)
            if not isinstance(values, list) or not values or not all(
                isinstance(item, str) and item.strip() for item in values
            ):
                raise GateRegisterError(f"gate_{field}_missing:{gate_id}")
        evidence = _mapping(gate.get("evidence"), f"gate_evidence_missing:{gate_id}")
        test_nodes = evidence.get("test_nodes")
        receipts = evidence.get("run_receipts")
        if not isinstance(test_nodes, list) or not all(
            isinstance(item, str) and item for item in test_nodes
        ):
            raise GateRegisterError(f"gate_test_nodes_invalid:{gate_id}")
        if not isinstance(receipts, list):
            raise GateRegisterError(f"gate_run_receipts_invalid:{gate_id}")
        if status == "partial" and not test_nodes:
            raise GateRegisterError(f"partial_gate_requires_test_node:{gate_id}")
        if status == "not_supported":
            _nonempty_string(gate.get("boundary"), f"unsupported_gate_requires_boundary:{gate_id}")
        if status == "done" and not test_nodes:
            raise GateRegisterError(f"done_gate_requires_test_node:{gate_id}")
        if status == "done" and not receipts:
            raise GateRegisterError(f"done_gate_requires_run_receipt:{gate_id}")
        for receipt in receipts:
            receipt_data = _mapping(receipt, f"gate_run_receipt_must_be_object:{gate_id}")
            missing = [field for field in receipt_fields if not receipt_data.get(field)]
            if missing:
                raise GateRegisterError(
                    f"run_receipt_fields_missing:{gate_id}:{','.join(sorted(missing))}"
                )
            _validate_run_receipt(receipt_data, gate_id)

    if referenced_usecase_ids != set(selected_by_id):
        raise GateRegisterError("selected_usecases_must_equal_gate_references")
    return register


def summarize_gate_register(register: object) -> dict[str, Any]:
    validated = validate_gate_register(register)
    counts = Counter(gate["status"] for gate in validated["gates"])
    ordered_counts = {status: counts[status] for status in sorted(ALLOWED_STATUSES)}
    open_gates = [
        gate["gate_id"] for gate in validated["gates"] if gate["status"] != "done"
    ]
    return {
        "complete": not open_gates,
        "counts": ordered_counts,
        "open_gates": open_gates,
    }


def verify_ellmos_catalog(register: object, catalog_path: str | Path) -> dict[str, Any]:
    validated = validate_gate_register(register)
    path = Path(catalog_path).resolve()
    raw = path.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    expected_sha = validated["source_catalog"]["sha256"]
    if actual_sha != expected_sha:
        raise GateRegisterError(
            f"ellmos_catalog_sha256_mismatch:expected={expected_sha}:actual={actual_sha}"
        )
    try:
        catalog = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateRegisterError("ellmos_catalog_invalid_json") from exc
    catalog_data = _mapping(catalog, "ellmos_catalog_must_be_object")
    usecases = catalog_data.get("usecases")
    if not isinstance(usecases, list):
        raise GateRegisterError("ellmos_catalog_usecases_must_be_list")
    actual_by_id = {
        item.get("id"): item for item in usecases if isinstance(item, dict) and "id" in item
    }
    selected = validated["source_catalog"]["selected_usecases"]
    for expected in selected:
        actual = actual_by_id.get(expected["id"])
        if actual is None or any(
            actual.get(field) != expected[field] for field in ("title", "description")
        ):
            raise GateRegisterError(f"ellmos_usecase_mismatch:{expected['id']}")
    return {
        "catalog_path": str(path),
        "catalog_verified": True,
        "selected_usecase_count": len(selected),
        "sha256": actual_sha,
    }


def _mapping(value: object, error: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GateRegisterError(error)
    return value


def _nonempty_string(value: object, error: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateRegisterError(error)
    return value


def _validate_run_receipt(receipt: dict[str, Any], gate_id: str) -> None:
    run_id = _nonempty_string(receipt.get("run_id"), f"run_receipt_run_id_invalid:{gate_id}")
    if run_id.lower() in {"present", "placeholder", "tbd", "todo", "unknown"}:
        raise GateRegisterError(f"run_receipt_run_id_placeholder:{gate_id}")
    for field in ("input_sha256", "output_sha256"):
        _validate_evidence_sha(receipt.get(field), gate_id, "run_receipt")

    handoffs = receipt.get("handoff_receipts")
    if not isinstance(handoffs, list) or not handoffs:
        raise GateRegisterError(f"handoff_receipts_must_be_nonempty_list:{gate_id}")
    for handoff in handoffs:
        item = _mapping(handoff, f"handoff_receipt_must_be_object:{gate_id}")
        for field in ("producer", "consumer", "artifact_path", "evidence"):
            _nonempty_string(item.get(field), f"handoff_receipt_{field}_missing:{gate_id}")
        _validate_evidence_sha(item.get("artifact_sha256"), gate_id, "handoff_receipt")
        if item.get("status") != "verified":
            raise GateRegisterError(f"handoff_receipt_not_verified:{gate_id}")

    run_report = _mapping(receipt.get("run_report"), f"run_report_must_be_object:{gate_id}")
    _nonempty_string(run_report.get("path"), f"run_report_path_missing:{gate_id}")
    _validate_evidence_sha(run_report.get("sha256"), gate_id, "run_report")
    if run_report.get("status") != "executed" or run_report.get("verified") is not True:
        raise GateRegisterError(f"run_report_not_verified_executed:{gate_id}")

    checks = receipt.get("result_checks")
    if not isinstance(checks, list) or not checks:
        raise GateRegisterError(f"result_checks_must_be_nonempty_list:{gate_id}")
    for check in checks:
        item = _mapping(check, f"result_check_must_be_object:{gate_id}")
        _nonempty_string(item.get("name"), f"result_check_name_missing:{gate_id}")
        _nonempty_string(item.get("evidence"), f"result_check_evidence_missing:{gate_id}")
        if item.get("passed") is not True:
            raise GateRegisterError(f"result_check_not_passed:{gate_id}")

    negative = _mapping(receipt.get("negative_path"), f"negative_path_must_be_object:{gate_id}")
    for field in ("case", "run_id", "evidence"):
        _nonempty_string(negative.get(field), f"negative_path_{field}_missing:{gate_id}")
    if negative.get("status") not in {"blocked", "failed"}:
        raise GateRegisterError(f"negative_path_status_invalid:{gate_id}")
    if negative.get("blocked_as_expected") is not True:
        raise GateRegisterError(f"negative_path_not_confirmed:{gate_id}")
    negative_report = _mapping(
        negative.get("run_report"), f"negative_path_run_report_must_be_object:{gate_id}"
    )
    _nonempty_string(
        negative_report.get("path"), f"negative_path_run_report_path_missing:{gate_id}"
    )
    _validate_evidence_sha(negative_report.get("sha256"), gate_id, "negative_path")


def _validate_evidence_sha(value: object, gate_id: str, prefix: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise GateRegisterError(f"{prefix}_sha256_invalid:{gate_id}")
    if len(set(value)) == 1:
        raise GateRegisterError(f"{prefix}_sha256_placeholder:{gate_id}")
    return value
