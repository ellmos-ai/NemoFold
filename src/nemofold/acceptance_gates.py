from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

EXPECTED_GATE_IDS = tuple(f"G{number:02d}" for number in range(1, 19))
ALLOWED_STATUSES = frozenset({"planned", "partial", "not_supported", "done"})
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER_VALUES = frozenset(
    {"n/a", "na", "none", "placeholder", "present", "tbd", "test", "todo", "unknown"}
)


class GateRegisterError(ValueError):
    """Raised when the acceptance register or its provenance is invalid."""


def _read_register_payload(path: str | Path | None) -> Any:
    if path is None:
        resource = files("nemofold").joinpath("data", "nf_fin_gates.json")
        raw = resource.read_text(encoding="utf-8")
    else:
        raw = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateRegisterError(f"invalid_gate_register_json:{exc.msg}") from exc


def load_gate_register(
    path: str | Path | None = None,
    *,
    evidence_root: str | Path | None = None,
) -> dict[str, Any]:
    return validate_gate_register(
        _read_register_payload(path), evidence_root=evidence_root
    )


def load_gate_register_template(path: str | Path | None = None) -> dict[str, Any]:
    """Load the register with collected evidence stripped, ready to be filled in.

    The shipped register carries ``done`` gates, and a ``done`` gate cannot be
    loaded without an evidence root holding its files. A bundle that is about to
    produce that evidence has no such root yet, so it starts from this template:
    every gate resting on run receipts falls back to ``planned`` and its receipts
    are dropped. Declared test nodes stay, because they are verified against the
    repository rather than against a run directory.
    """
    register = _read_register_payload(path)
    for gate in register.get("gates", []) if isinstance(register, dict) else []:
        if not isinstance(gate, dict):
            continue
        evidence = gate.get("evidence")
        if isinstance(evidence, dict) and evidence.get("run_receipts"):
            evidence["run_receipts"] = []
            if gate.get("status") == "done":
                gate["status"] = "planned"
    return validate_gate_register(register)


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
    evidenced_gates: list[dict[str, Any]] = []
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
        if not isinstance(test_nodes, list):
            raise GateRegisterError(f"gate_test_nodes_invalid:{gate_id}")
        seen_nodes: set[str] = set()
        for raw_node in test_nodes:
            node = _mapping(raw_node, f"gate_test_node_must_be_object:{gate_id}")
            node_id = _nonplaceholder_string(
                node.get("node"),
                f"gate_test_node_missing:{gate_id}",
                f"gate_test_node_placeholder:{gate_id}",
            )
            _validate_evidence_sha(node.get("file_sha256"), gate_id, "test_node")
            if node_id in seen_nodes:
                raise GateRegisterError(f"duplicate_test_node:{gate_id}:{node_id}")
            seen_nodes.add(node_id)
        if not isinstance(receipts, list):
            raise GateRegisterError(f"gate_run_receipts_invalid:{gate_id}")
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
        if receipts:
            evidenced_gates.append(gate)

    if referenced_usecase_ids != set(selected_by_id):
        raise GateRegisterError("selected_usecases_must_equal_gate_references")
    if done_gates and evidence_root is None:
        raise GateRegisterError(
            f"done_gate_requires_evidence_root:{done_gates[0]['gate_id']}"
        )
    if evidenced_gates:
        if evidence_root is None:
            raise GateRegisterError(
                f"gate_receipts_require_evidence_root:{evidenced_gates[0]['gate_id']}"
            )
        _verify_done_gate_files(evidenced_gates, evidence_root)
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
    evidenced_gates = [
        gate for gate in validated["gates"] if gate["evidence"]["run_receipts"]
    ]
    done_gates = [gate for gate in validated["gates"] if gate["status"] == "done"]
    checked_files = _verify_done_gate_files(evidenced_gates, evidence_root)
    return {
        "evidence_root": str(Path(evidence_root).resolve()),
        "verified_evidence_gates": [gate["gate_id"] for gate in evidenced_gates],
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


def _nonplaceholder_string(value: object, error: str, placeholder_error: str) -> str:
    text = _nonempty_string(value, error)
    if text.strip().casefold() in PLACEHOLDER_VALUES:
        raise GateRegisterError(placeholder_error)
    return text


def _validate_run_receipt(receipt: dict[str, Any], gate_id: str) -> None:
    _nonplaceholder_string(
        receipt.get("run_id"),
        f"run_receipt_run_id_invalid:{gate_id}",
        f"run_receipt_run_id_placeholder:{gate_id}",
    )
    artifact_paths: dict[str, set[str]] = {"input": set(), "output": set()}
    for field in ("input_sha256", "output_sha256"):
        _validate_evidence_sha(receipt.get(field), gate_id, "run_receipt")
    for direction in ("input", "output"):
        artifacts = receipt.get(f"{direction}_artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise GateRegisterError(
                f"{direction}_artifacts_must_be_nonempty_list:{gate_id}"
            )
        for artifact in artifacts:
            item = _mapping(artifact, f"{direction}_artifact_must_be_object:{gate_id}")
            path = _nonempty_string(
                item.get("path"), f"{direction}_artifact_path_missing:{gate_id}"
            )
            canonical_path = _canonical_relative_path(path, gate_id, f"{direction}_artifact")
            path_identity = _path_identity(canonical_path)
            if path_identity in artifact_paths[direction]:
                raise GateRegisterError(
                    f"duplicate_{direction}_artifact:{gate_id}:{canonical_path}"
                )
            artifact_paths[direction].add(path_identity)
            _validate_evidence_sha(
                item.get("sha256"), gate_id, f"{direction}_artifact"
            )
        expected_manifest_sha = artifact_manifest_sha256(artifacts)
        if receipt[f"{direction}_sha256"] != expected_manifest_sha:
            raise GateRegisterError(
                f"{direction}_manifest_sha256_mismatch:{gate_id}:"
                f"expected={receipt[f'{direction}_sha256']}:actual={expected_manifest_sha}"
            )
    overlap = artifact_paths["input"] & artifact_paths["output"]
    if overlap:
        raise GateRegisterError(
            f"artifact_used_as_input_and_output:{gate_id}:{sorted(overlap)[0]}"
        )
    claimed_paths = artifact_paths["input"] | artifact_paths["output"]

    handoffs = receipt.get("handoff_receipts")
    if not isinstance(handoffs, list) or not handoffs:
        raise GateRegisterError(f"handoff_receipts_must_be_nonempty_list:{gate_id}")
    handoff_paths: set[str] = set()
    for handoff in handoffs:
        item = _mapping(handoff, f"handoff_receipt_must_be_object:{gate_id}")
        for field in ("producer", "consumer", "evidence"):
            _nonplaceholder_string(
                item.get(field),
                f"handoff_receipt_{field}_missing:{gate_id}",
                f"handoff_receipt_{field}_placeholder:{gate_id}",
            )
        handoff_path = _canonical_relative_path(
            item.get("artifact_path"), gate_id, "handoff_receipt"
        )
        handoff_identity = _path_identity(handoff_path)
        if handoff_identity in handoff_paths:
            raise GateRegisterError(f"duplicate_handoff_receipt:{gate_id}:{handoff_path}")
        if handoff_identity in claimed_paths:
            raise GateRegisterError(
                f"evidence_path_role_conflict:{gate_id}:handoff_receipt:{handoff_path}"
            )
        handoff_paths.add(handoff_identity)
        claimed_paths.add(handoff_identity)
        _validate_evidence_sha(item.get("artifact_sha256"), gate_id, "handoff_receipt")
        if item.get("status") != "verified":
            raise GateRegisterError(f"handoff_receipt_not_verified:{gate_id}")

    run_report = _mapping(receipt.get("run_report"), f"run_report_must_be_object:{gate_id}")
    positive_report_path = _canonical_relative_path(
        run_report.get("path"), gate_id, "run_report"
    )
    positive_report_identity = _path_identity(positive_report_path)
    if positive_report_identity in claimed_paths:
        raise GateRegisterError(
            f"evidence_path_role_conflict:{gate_id}:run_report:{positive_report_path}"
        )
    claimed_paths.add(positive_report_identity)
    _validate_evidence_sha(run_report.get("sha256"), gate_id, "run_report")
    if run_report.get("status") != "executed" or run_report.get("verified") is not True:
        raise GateRegisterError(f"run_report_not_verified_executed:{gate_id}")

    checks = receipt.get("result_checks")
    if not isinstance(checks, list) or not checks:
        raise GateRegisterError(f"result_checks_must_be_nonempty_list:{gate_id}")
    for check in checks:
        item = _mapping(check, f"result_check_must_be_object:{gate_id}")
        _nonplaceholder_string(
            item.get("name"),
            f"result_check_name_missing:{gate_id}",
            f"result_check_name_placeholder:{gate_id}",
        )
        _nonplaceholder_string(
            item.get("evidence"),
            f"result_check_evidence_missing:{gate_id}",
            f"result_check_evidence_placeholder:{gate_id}",
        )
        if item.get("passed") is not True:
            raise GateRegisterError(f"result_check_not_passed:{gate_id}")

    additional = receipt.get("additional_negative_paths", [])
    if not isinstance(additional, list) or len(additional) > 20:
        raise GateRegisterError(
            f"additional_negative_paths_must_be_bounded_list:{gate_id}"
        )
    negative_paths = [
        _mapping(
            receipt.get("negative_path"),
            f"negative_path_must_be_object:{gate_id}",
        ),
        *(
            _mapping(item, f"additional_negative_path_must_be_object:{gate_id}")
            for item in additional
        ),
    ]
    negative_run_ids: set[str] = set()
    negative_cases: set[str] = set()
    for index, negative in enumerate(negative_paths):
        prefix = "negative_path" if index == 0 else "additional_negative_path"
        values = {}
        for field in ("case", "run_id", "evidence"):
            values[field] = _nonplaceholder_string(
                negative.get(field),
                f"{prefix}_{field}_missing:{gate_id}",
                f"{prefix}_{field}_placeholder:{gate_id}",
            )
        normalized_case = values["case"].strip().casefold()
        if normalized_case in negative_cases:
            raise GateRegisterError(f"duplicate_negative_case:{gate_id}")
        negative_cases.add(normalized_case)
        if negative.get("status") not in {"blocked", "failed"}:
            raise GateRegisterError(f"{prefix}_status_invalid:{gate_id}")
        if negative.get("blocked_as_expected") is not True:
            raise GateRegisterError(f"{prefix}_not_confirmed:{gate_id}")
        negative_run_id = values["run_id"]
        if negative_run_id == receipt.get("run_id"):
            raise GateRegisterError(f"positive_and_negative_run_id_same:{gate_id}")
        if negative_run_id in negative_run_ids:
            raise GateRegisterError(f"duplicate_negative_run_id:{gate_id}")
        negative_run_ids.add(negative_run_id)
        negative_report = _mapping(
            negative.get("run_report"),
            f"{prefix}_run_report_must_be_object:{gate_id}",
        )
        negative_report_path = _canonical_relative_path(
            negative_report.get("path"), gate_id, prefix
        )
        negative_report_identity = _path_identity(negative_report_path)
        if negative_report_identity in claimed_paths:
            if negative_report_identity == positive_report_identity:
                raise GateRegisterError(
                    f"positive_and_negative_run_report_same_path:{gate_id}"
                )
            raise GateRegisterError(
                f"evidence_path_role_conflict:{gate_id}:{prefix}:"
                f"{negative_report_path}"
            )
        claimed_paths.add(negative_report_identity)
        _validate_evidence_sha(
            negative_report.get("sha256"), gate_id, prefix
        )


def _validate_evidence_sha(value: object, gate_id: str, prefix: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise GateRegisterError(f"{prefix}_sha256_invalid:{gate_id}")
    if len(set(value)) == 1:
        raise GateRegisterError(f"{prefix}_sha256_placeholder:{gate_id}")
    return value


def _canonical_relative_path(value: object, gate_id: str, kind: str) -> str:
    path_text = _nonempty_string(value, f"evidence_path_missing:{gate_id}:{kind}")
    declared = Path(path_text)
    if declared.is_absolute():
        raise GateRegisterError(f"evidence_path_must_be_relative:{gate_id}:{kind}:{path_text}")
    if ".." in declared.parts:
        raise GateRegisterError(f"evidence_path_traversal:{gate_id}:{kind}:{path_text}")
    return declared.as_posix()


def _path_identity(path: str) -> str:
    return os.path.normcase(str(Path(path))).replace("\\", "/")


def artifact_manifest_sha256(artifacts: Sequence[object]) -> str:
    """Hash the canonical path/hash list used by a gate run receipt."""
    canonical = json.dumps(
        list(artifacts),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def require_ledger_path(ledger_path: str | None, context: str) -> Path:
    """Return a completed step's ledger path, failing loudly when it was never written."""
    if ledger_path is None:
        raise GateRegisterError(f"ledger_path_missing:{context}")
    return Path(ledger_path)


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
            checked.append(_verify_test_node(root, node, gate_id))
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
                _verify_run_report_file(
                    root,
                    receipt["run_report"],
                    gate_id,
                    expected_run_id=receipt["run_id"],
                    expected_status=receipt["run_report"]["status"],
                    kind="run_report",
                )
            )
            negative_paths = [
                receipt["negative_path"],
                *receipt.get("additional_negative_paths", []),
            ]
            for index, negative in enumerate(negative_paths):
                kind = "negative_path" if index == 0 else "additional_negative_path"
                checked.append(
                    _verify_run_report_file(
                        root,
                        negative["run_report"],
                        gate_id,
                        expected_run_id=negative["run_id"],
                        expected_status=negative["status"],
                        kind=kind,
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
    path_text = _canonical_relative_path(relative_path, gate_id, kind)
    declared = Path(path_text)
    candidate = (root / declared).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise GateRegisterError(
            f"evidence_path_outside_root:{gate_id}:{kind}:{path_text}"
        ) from exc
    if not candidate.is_file():
        raise GateRegisterError(f"evidence_file_missing:{gate_id}:{kind}:{path_text}")
    raw = candidate.read_bytes()
    if expected_sha256 is not None:
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if actual_sha256 != expected_sha256:
            raise GateRegisterError(
                f"evidence_sha256_mismatch:{gate_id}:{kind}:{path_text}:"
                f"expected={expected_sha256}:actual={actual_sha256}"
            )
    stripped = raw.strip().lower()
    if not stripped:
        raise GateRegisterError(f"evidence_file_empty:{gate_id}:{kind}:{path_text}")
    placeholder_bytes = {value.encode("utf-8") for value in PLACEHOLDER_VALUES}
    if stripped in placeholder_bytes:
        raise GateRegisterError(f"evidence_file_placeholder:{gate_id}:{kind}:{path_text}")
    return candidate.relative_to(root).as_posix()


def _verify_test_node(root: Path, node: dict[str, Any], gate_id: str) -> str:
    node_id = node["node"]
    path_text, separator, selector_text = node_id.partition("::")
    if not separator or not selector_text:
        raise GateRegisterError(f"test_node_selector_missing:{gate_id}:{node_id}")
    relative = _verify_evidence_file(
        root,
        path_text,
        node["file_sha256"],
        gate_id,
        "test_node",
    )
    candidate = root / relative
    if candidate.suffix.casefold() != ".py":
        raise GateRegisterError(f"test_node_not_python:{gate_id}:{node_id}")
    try:
        tree = ast.parse(candidate.read_text(encoding="utf-8"), filename=str(candidate))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise GateRegisterError(f"test_node_invalid_python:{gate_id}:{node_id}") from exc
    selectors = [part.split("[", 1)[0] for part in selector_text.split("::")]
    if not _ast_contains_test_node(tree, selectors):
        raise GateRegisterError(f"test_node_not_found:{gate_id}:{node_id}")
    return relative


def _ast_contains_test_node(tree: ast.Module, selectors: list[str]) -> bool:
    if len(selectors) == 1:
        return any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == selectors[0]
            and node.name.startswith("test_")
            for node in tree.body
        )
    if len(selectors) == 2:
        return any(
            isinstance(node, ast.ClassDef)
            and node.name == selectors[0]
            and node.name.startswith("Test")
            and any(
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name == selectors[1]
                and child.name.startswith("test_")
                for child in node.body
            )
            for node in tree.body
        )
    return False


def _verify_run_report_file(
    root: Path,
    report: dict[str, Any],
    gate_id: str,
    *,
    expected_run_id: str,
    expected_status: str,
    kind: str,
) -> str:
    relative = _verify_evidence_file(
        root,
        report["path"],
        report["sha256"],
        gate_id,
        kind,
    )
    try:
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateRegisterError(f"{kind}_invalid_json:{gate_id}:{relative}") from exc
    data = _mapping(payload, f"{kind}_must_contain_object:{gate_id}:{relative}")
    if data.get("run_id") != expected_run_id:
        raise GateRegisterError(f"{kind}_run_id_mismatch:{gate_id}:{relative}")
    if data.get("status") != expected_status:
        raise GateRegisterError(f"{kind}_status_mismatch:{gate_id}:{relative}")
    return relative
