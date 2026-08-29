from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import write_text_artifact
from .contracts import GateDecision, JobEnvelope
from .evidence_analyst import ContextReceipt

PACKAGE_SCHEMA = "nemofold.nemoclaw-job.v1"


@dataclass(frozen=True, slots=True)
class NemoClawPackage:
    path: Path
    run_id: str
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class PackageValidation:
    valid: bool
    run_id: str | None
    errors: tuple[str, ...]


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _contains_forbidden_path(value: Any) -> bool:
    if isinstance(value, Mapping):
        if any(str(key).casefold() in {"path", "input_roots", "output_dir"} for key in value):
            return True
        return any(_contains_forbidden_path(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_forbidden_path(item) for item in value)
    if isinstance(value, str):
        return bool(
            re.search(r"(?i)\b[a-z]:[\\/]", value)
            or re.search(r"/(?:home|users|root|private|mnt)/", value, flags=re.IGNORECASE)
        )
    return False


def export_job_package(
    job: JobEnvelope,
    receipts: Sequence[ContextReceipt],
    decision: GateDecision,
    destination: str | Path,
    *,
    run_id: str,
) -> NemoClawPackage:
    if not decision.allowed or decision.recipient != "nebius":
        raise PermissionError("a positive Nebius gate decision is required")
    if not job.requires_external_model:
        raise ValueError("NemoClaw package requires an external model declaration")
    if not run_id or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("run_id contains unsafe characters")
    source_ids = {source.source_id for source in job.sources}
    for receipt in receipts:
        if receipt.question not in job.questions:
            raise ValueError("context receipt question is not declared by the job")
        if any(hit.source_id not in source_ids for hit in receipt.hits):
            raise ValueError("context receipt contains an undeclared source ID")

    package_path = Path(destination)
    package_path.mkdir(parents=True, exist_ok=False)
    job_payload = {**job.to_external_payload(), "run_id": run_id}
    receipt_payload = [receipt.to_payload() for receipt in receipts]
    if _contains_forbidden_path(job_payload) or _contains_forbidden_path(receipt_payload):
        raise ValueError("external package contains a host path")
    job_bytes = _json_bytes(job_payload)
    receipt_bytes = _json_bytes(receipt_payload)
    write_text_artifact(package_path / "job.json", job_bytes.decode(), "nemoclaw-job")
    write_text_artifact(
        package_path / "context-receipts.json",
        receipt_bytes.decode(),
        "context-receipts",
    )
    manifest = {
        "schema": PACKAGE_SCHEMA,
        "run_id": run_id,
        "files": {
            "job.json": _sha256(job_bytes),
            "context-receipts.json": _sha256(receipt_bytes),
        },
        "expected_result": "result.json",
    }
    manifest_bytes = _json_bytes(manifest)
    write_text_artifact(
        package_path / "manifest.json", manifest_bytes.decode(), "nemoclaw-manifest"
    )
    validation = validate_job_package(package_path)
    if not validation.valid:
        raise RuntimeError(f"created invalid package: {', '.join(validation.errors)}")
    return NemoClawPackage(
        path=package_path,
        run_id=run_id,
        manifest_sha256=_sha256(manifest_bytes),
    )


def validate_job_package(path: str | Path) -> PackageValidation:
    package_path = Path(path)
    errors: list[str] = []
    run_id: str | None = None
    if not package_path.is_dir() or package_path.is_symlink():
        return PackageValidation(False, None, ("package_directory_invalid",))
    try:
        manifest = json.loads((package_path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return PackageValidation(False, None, ("manifest_invalid",))
    if manifest.get("schema") != PACKAGE_SCHEMA:
        errors.append("manifest_schema_invalid")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        errors.append("run_id_invalid")

    expected_files = manifest.get("files")
    if not isinstance(expected_files, dict):
        errors.append("manifest_files_invalid")
        expected_files = {}
    for filename, expected_hash in expected_files.items():
        file_path = package_path / filename
        if file_path.parent != package_path or not file_path.is_file() or file_path.is_symlink():
            errors.append(f"file_invalid:{filename}")
            continue
        if _sha256(file_path.read_bytes()) != expected_hash:
            errors.append(f"hash_mismatch:{filename}")

    try:
        job = json.loads((package_path / "job.json").read_text(encoding="utf-8"))
        receipts = json.loads(
            (package_path / "context-receipts.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        errors.append("package_json_invalid")
        return PackageValidation(not errors, run_id, tuple(errors))
    if job.get("run_id") != run_id:
        errors.append("job_run_id_mismatch")
    if not isinstance(job.get("model"), dict) or not job["model"].get("id"):
        errors.append("model_missing")
    if _contains_forbidden_path(job) or _contains_forbidden_path(receipts):
        errors.append("host_path_detected")
    declared_sources = {
        item.get("source_id") for item in job.get("sources", []) if isinstance(item, dict)
    }
    for receipt in receipts if isinstance(receipts, list) else ():
        if not isinstance(receipt, dict):
            errors.append("receipt_invalid")
            continue
        for chunk in receipt.get("chunks", []):
            if not isinstance(chunk, dict) or chunk.get("source_id") not in declared_sources:
                errors.append("receipt_source_not_declared")
    return PackageValidation(not errors, run_id, tuple(errors))
