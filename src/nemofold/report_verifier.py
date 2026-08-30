from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import RunStatus


@dataclass(frozen=True, slots=True)
class ReportVerification:
    valid: bool
    run_id: str | None
    errors: tuple[str, ...]
    checked_artifacts: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _coverage_valid(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    total_value = value.get("total_sources")
    read_value = value.get("read_sources")
    cited_value = value.get("cited_sources")
    counts = (total_value, read_value, cited_value)
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in counts):
        return False
    if not all(isinstance(item, int) for item in counts):
        return False
    assert isinstance(total_value, int)
    assert isinstance(read_value, int)
    assert isinstance(cited_value, int)
    total, read, cited = total_value, read_value, cited_value
    unread = value.get("unread_source_ids", [])
    uncited = value.get("uncited_read_source_ids", [])
    return (
        cited <= read <= total
        and isinstance(unread, list)
        and isinstance(uncited, list)
        and all(isinstance(item, str) for item in unread + uncited)
        and len(set(unread)) == len(unread)
        and len(set(uncited)) == len(uncited)
        and not set(unread).intersection(uncited)
        and len(unread) == total - read
        and len(uncited) == read - cited
    )


def verify_run_report(path: str | Path) -> ReportVerification:
    report_path = Path(path).resolve()
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ReportVerification(False, None, ("report_json_invalid",), 0)
    if not isinstance(payload, dict):
        return ReportVerification(False, None, ("report_contract_invalid",), 0)

    errors: list[str] = []
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        errors.append("run_id_invalid")
        run_id = None
    status_value = payload.get("status")
    try:
        status = RunStatus(status_value) if isinstance(status_value, str) else None
    except ValueError:
        status = None
    if status is None:
        errors.append("status_invalid")
    if not isinstance(payload.get("workflow"), str) or not payload["workflow"]:
        errors.append("workflow_invalid")
    key = payload.get("idempotency_key")
    if not isinstance(key, str) or not re.fullmatch(r"job_[0-9a-f]{64}", key):
        errors.append("idempotency_key_invalid")

    report_errors = payload.get("errors", [])
    if not isinstance(report_errors, list) or any(
        not isinstance(item, str) for item in report_errors
    ):
        errors.append("errors_invalid")
    elif status is RunStatus.EXECUTED and report_errors:
        errors.append("executed_report_has_errors")
    elif status in {RunStatus.BLOCKED, RunStatus.FAILED} and not report_errors:
        errors.append("non_success_report_missing_error")

    coverage = payload.get("coverage")
    if coverage is not None and not _coverage_valid(coverage):
        errors.append("coverage_counts_invalid")

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        errors.append("metadata_invalid")
        metadata = {}
    if metadata.get("cloud_proof") is True:
        evidence = metadata.get("live_runtime_evidence")
        required = {"nemoclaw_version", "model_id", "verbatim_log_sha256"}
        if not isinstance(evidence, dict) or not required.issubset(evidence):
            errors.append("cloud_proof_evidence_missing")

    artifacts = payload.get("artifacts", [])
    if not isinstance(artifacts, list):
        errors.append("artifacts_invalid")
        artifacts = []
    run_root = (
        report_path.parent.parent if report_path.parent.name == "ledger" else report_path.parent
    )
    checked = 0
    seen_paths: set[Path] = set()
    for item in artifacts:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            errors.append("artifact_contract_invalid")
            continue
        artifact = Path(item["path"]).resolve()
        label = artifact.name or "unknown"
        if artifact in seen_paths:
            errors.append(f"artifact_duplicate:{label}")
            continue
        seen_paths.add(artifact)
        if not artifact.is_relative_to(run_root):
            errors.append(f"artifact_outside_run_root:{label}")
            continue
        if not artifact.is_file() or artifact.is_symlink():
            errors.append(f"artifact_missing:{label}")
            continue
        expected = item.get("sha256")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            errors.append(f"artifact_hash_invalid:{label}")
            continue
        checked += 1
        if _sha256(artifact) != expected:
            errors.append(f"artifact_hash_mismatch:{label}")

    return ReportVerification(not errors, run_id, tuple(errors), checked)
