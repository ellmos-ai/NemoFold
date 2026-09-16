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


def load_gate_register(
    path: str | Path | None = None,
    *,
    evidence_root: str | Path | None = None,
) -> dict[str, Any]:
    if path is None:
        resource = files("nemofold").joinpath("data", "nf_fin_gates.json")
        raw = resource.read_text(encoding="utf-8")
    else:
        raw = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateRegisterError(f"invalid_gate_register_json:{exc.msg}") from exc
    return validate_gate_register(payload, evidence_root=evidence_root)


def validate_gate_register(
    payload: object,
    *,
    evidence_root: str | Path | None = None,
) -> dict[str, Any]:
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
    done_gates: list[dict[str, Any]] = []
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
        if status == "done":
            done_gates.append(gate)

    if referenced_usecase_ids != set(selected_by_id):
        raise GateRegisterError("selected_usecases_must_equal_gate_references")
    if done_gates:
        if evidence_root is None:
            raise GateRegisterError(
                f"done_gate_requires_evidence_root:{done_gates[0]['gate_id']}"
            )
        _verify_done_gate_files(done_gates, evidence_root)
    return register


def summarize_gate_register(
    register: object,
    *,
    evidence_root: str | Path | None = None,
) -> dict[str, Any]:
    validated = validate_gate_register(register, evidence_root=evidence_root)
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


def verify_ellmos_catalog(
    register: object,
    catalog_path: str | Path,
    *,
    evidence_root: str | Path | None = None,
) -> dict[str, Any]:
    validated = validate_gate_register(register, evidence_root=evidence_root)
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


def verify_gate_evidence(
    register: object,
    evidence_root: str | Path,
) -> dict[str, Any]:
    validated = validate_gate_register(register, evidence_root=evidence_root)
    done_gates = [gate for gate in validated["gates"] if gate["status"] == "done"]
    checked_files = _verify_done_gate_files(done_gates, evidence_root)
    return {
        "evidence_root": str(Path(evidence_root).resolve()),
        "verified_done_gates": [gate["gate_id"] for gate in done_gates],
        "checked_file_count": len(checked_files),
        "checked_files": checked_files,
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
    for direction in ("input", "output"):
        artifacts = receipt.get(f"{direction}_artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise GateRegisterError(
                f"{direction}_artifacts_must_be_nonempty_list:{gate_id}"
            )
        seen_paths: set[str] = set()
        for artifact in artifacts:
            item = _mapping(artifact, f"{direction}_artifact_must_be_object:{gate_id}")
            path = _nonempty_string(
                item.get("path"), f"{direction}_artifact_path_missing:{gate_id}"
            )
            if path in seen_paths:
                raise GateRegisterError(f"duplicate_{direction}_artifact:{gate_id}:{path}")
            seen_paths.add(path)
            _validate_evidence_sha(
                item.get("sha256"), gate_id, f"{direction}_artifact"
            )
        expected_manifest_sha = _artifact_manifest_sha256(artifacts)
        if receipt[f"{direction}_sha256"] != expected_manifest_sha:
            raise GateRegisterError(
                f"{direction}_manifest_sha256_mismatch:{gate_id}:"
                f"expected={receipt[f'{direction}_sha256']}:actual={expected_manifest_sha}"
            )

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


def _artifact_manifest_sha256(artifacts: list[object]) -> str:
    canonical = json.dumps(
        artifacts,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _verify_done_gate_files(
    done_gates: list[dict[str, Any]],
    evidence_root: str | Path,
) -> list[str]:
    root = Path(evidence_root).resolve()
    if not root.is_dir():
        raise GateRegisterError(f"evidence_root_not_directory:{root}")
    checked: list[str] = []
    for gate in done_gates:
        gate_id = gate["gate_id"]
        for node in gate["evidence"]["test_nodes"]:
            test_path = node.split("::", 1)[0]
            checked.append(
                _verify_evidence_file(root, test_path, None, gate_id, "test_node")
            )
        for receipt in gate["evidence"]["run_receipts"]:
            for direction in ("input", "output"):
                for artifact in receipt[f"{direction}_artifacts"]:
                    checked.append(
                        _verify_evidence_file(
                            root,
                            artifact["path"],
                            artifact["sha256"],
                            gate_id,
                            f"{direction}_artifact",
                        )
                    )
            for handoff in receipt["handoff_receipts"]:
                checked.append(
                    _verify_evidence_file(
                        root,
                        handoff["artifact_path"],
                        handoff["artifact_sha256"],
                        gate_id,
                        "handoff_receipt",
                    )
                )
            checked.append(
                _verify_evidence_file(
                    root,
                    receipt["run_report"]["path"],
                    receipt["run_report"]["sha256"],
                    gate_id,
                    "run_report",
                )
            )
            negative_report = receipt["negative_path"]["run_report"]
            checked.append(
                _verify_evidence_file(
                    root,
                    negative_report["path"],
                    negative_report["sha256"],
                    gate_id,
                    "negative_path",
                )
            )
    return sorted(set(checked))


def _verify_evidence_file(
    root: Path,
    relative_path: object,
    expected_sha256: str | None,
    gate_id: str,
    kind: str,
) -> str:
    path_text = _nonempty_string(relative_path, f"evidence_path_missing:{gate_id}:{kind}")
    declared = Path(path_text)
    if declared.is_absolute():
        raise GateRegisterError(f"evidence_path_must_be_relative:{gate_id}:{kind}:{path_text}")
    candidate = (root / declared).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise GateRegisterError(
            f"evidence_path_outside_root:{gate_id}:{kind}:{path_text}"
        ) from exc
    if not candidate.is_file():
        raise GateRegisterError(f"evidence_file_missing:{gate_id}:{kind}:{path_text}")
    if expected_sha256 is not None:
        actual_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise GateRegisterError(
                f"evidence_sha256_mismatch:{gate_id}:{kind}:{path_text}:"
                f"expected={expected_sha256}:actual={actual_sha256}"
            )
    return candidate.relative_to(root).as_posix()
