from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .anonymizer import detect_sensitive_categories, pseudonymize_questions_and_receipts
from .artifacts import write_text_artifact
from .contracts import CONTRACT_VERSION, GateDecision, JobEnvelope
from .evidence_analyst import ContextReceipt

PACKAGE_SCHEMA = "nemofold.nemoclaw-job.v1"
TRANSFER_ATTEMPT_FILENAME = "transfer-attempt.json"
ALLOWED_JOB_FIELDS = frozenset(
    {
        "contract_version",
        "model",
        "questions",
        "response_schema",
        "run_id",
        "sources",
        "validation_command",
        "workflow",
    }
)
ALLOWED_RECEIPT_FIELDS = frozenset({"chunks", "question", "response_schema"})
ALLOWED_CHUNK_FIELDS = frozenset(
    {
        "char_end",
        "char_start",
        "chunk_id",
        "line_end",
        "line_start",
        "page_end",
        "page_start",
        "source_id",
        "text",
    }
)


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
    sensitive_terms: Sequence[str] = (),
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
    pseudonymized = pseudonymize_questions_and_receipts(
        job.questions,
        receipts,
        sensitive_terms=sensitive_terms,
    )
    job_payload = {
        **job.to_external_payload(),
        "questions": list(pseudonymized.questions),
        "run_id": run_id,
        "validation_command": ["python", "-m", "nemofold", "verify-job", "."],
    }
    undeclared_fields = set(job_payload) - set(decision.allowed_fields)
    if undeclared_fields:
        raise PermissionError(
            f"external payload fields were not allowed: {', '.join(sorted(undeclared_fields))}"
        )
    receipt_payload = [receipt.to_payload() for receipt in pseudonymized.receipts]
    privacy_payload = {
        "schema": "nemofold.privacy-receipt.v1",
        "replacement_counts": pseudonymized.replacement_counts,
        "source_names_removed": True,
        "raw_mapping_stored": False,
        "transfer_performed": False,
    }
    if _contains_forbidden_path(job_payload) or _contains_forbidden_path(receipt_payload):
        raise ValueError("external package contains a host path")
    job_bytes = _json_bytes(job_payload)
    receipt_bytes = _json_bytes(receipt_payload)
    privacy_bytes = _json_bytes(privacy_payload)
    write_text_artifact(package_path / "job.json", job_bytes.decode(), "nemoclaw-job")
    write_text_artifact(
        package_path / "context-receipts.json",
        receipt_bytes.decode(),
        "context-receipts",
    )
    write_text_artifact(
        package_path / "privacy-receipt.json",
        privacy_bytes.decode(),
        "privacy-receipt",
    )
    manifest = {
        "schema": PACKAGE_SCHEMA,
        "run_id": run_id,
        "files": {
            "job.json": _sha256(job_bytes),
            "context-receipts.json": _sha256(receipt_bytes),
            "privacy-receipt.json": _sha256(privacy_bytes),
        },
        "expected_attempt": TRANSFER_ATTEMPT_FILENAME,
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
    required_files = {"job.json", "context-receipts.json", "privacy-receipt.json"}
    if not required_files.issubset(expected_files):
        errors.append("manifest_required_files_missing")
    if set(expected_files) != required_files:
        errors.append("manifest_file_set_invalid")
    if manifest.get("expected_result") != "result.json":
        errors.append("expected_result_invalid")
    if manifest.get("expected_attempt") != TRANSFER_ATTEMPT_FILENAME:
        errors.append("expected_attempt_invalid")
    for filename, expected_hash in expected_files.items():
        if not isinstance(filename, str) or not isinstance(expected_hash, str):
            errors.append("manifest_file_entry_invalid")
            continue
        file_path = package_path / filename
        if file_path.parent != package_path or not file_path.is_file() or file_path.is_symlink():
            errors.append(f"file_invalid:{filename}")
            continue
        if _sha256(file_path.read_bytes()) != expected_hash:
            errors.append(f"hash_mismatch:{filename}")
    try:
        present_entries = tuple(package_path.iterdir())
    except OSError:
        present_entries = ()
        errors.append("package_directory_unreadable")
    expected_result = manifest.get("expected_result")
    declared_names = set(expected_files) | {"manifest.json"}
    expected_attempt = manifest.get("expected_attempt")
    if isinstance(expected_attempt, str):
        declared_names.add(expected_attempt)
    if isinstance(expected_result, str):
        declared_names.add(expected_result)
    for entry in present_entries:
        if entry.name not in declared_names:
            errors.append(f"undeclared_entry:{entry.name}")
        if entry.is_symlink() or not entry.is_file():
            errors.append(f"package_entry_invalid:{entry.name}")

    try:
        job = json.loads((package_path / "job.json").read_text(encoding="utf-8"))
        receipts = json.loads(
            (package_path / "context-receipts.json").read_text(encoding="utf-8")
        )
        privacy = json.loads(
            (package_path / "privacy-receipt.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        errors.append("package_json_invalid")
        return PackageValidation(not errors, run_id, tuple(errors))
    if job.get("run_id") != run_id:
        errors.append("job_run_id_mismatch")
    if set(job) - ALLOWED_JOB_FIELDS:
        errors.append("job_fields_forbidden")
    if job.get("contract_version") != CONTRACT_VERSION:
        errors.append("contract_version_invalid")
    if job.get("response_schema") != "nemofold.claims.v1":
        errors.append("response_schema_invalid")
    if not isinstance(privacy, dict) or privacy.get("schema") != "nemofold.privacy-receipt.v1":
        errors.append("privacy_receipt_invalid")
    elif (
        privacy.get("source_names_removed") is not True
        or privacy.get("raw_mapping_stored") is not False
        or privacy.get("transfer_performed") is not False
    ):
        errors.append("privacy_receipt_invariant_invalid")
    replacement_counts = privacy.get("replacement_counts") if isinstance(privacy, dict) else None
    if not isinstance(replacement_counts, dict) or any(
        not isinstance(key, str)
        or isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        for key, value in replacement_counts.items()
    ):
        errors.append("privacy_replacement_counts_invalid")
    model = job.get("model")
    if not isinstance(model, dict) or set(model) != {"id", "max_cost_usd"}:
        errors.append("model_missing")
    else:
        if not isinstance(model.get("id"), str) or not model["id"]:
            errors.append("model_id_invalid")
        cost = model.get("max_cost_usd")
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(cost)
            or cost <= 0
        ):
            errors.append("model_budget_invalid")
    if job.get("validation_command") != ["python", "-m", "nemofold", "verify-job", "."]:
        errors.append("validation_command_invalid")
    if _contains_forbidden_path(job) or _contains_forbidden_path(receipts):
        errors.append("host_path_detected")
    source_values = job.get("sources")
    if not isinstance(source_values, list):
        errors.append("sources_invalid")
        source_values = []
    declared_source_list: list[str] = []
    allowed_source_fields = {"source_id", "mime_type", "sha256"}
    for source in source_values:
        if not isinstance(source, dict) or set(source) - allowed_source_fields:
            errors.append("source_metadata_forbidden")
            continue
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not re.fullmatch(
            r"src_[A-Za-z0-9_-]+", source_id
        ):
            errors.append("source_id_invalid")
        else:
            declared_source_list.append(source_id)
        if not isinstance(source.get("mime_type"), str) or not source["mime_type"]:
            errors.append("source_mime_type_invalid")
        if not isinstance(source.get("sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", source["sha256"]
        ):
            errors.append("source_hash_invalid")
    if len(set(declared_source_list)) != len(declared_source_list):
        errors.append("source_id_duplicate")
    declared_sources = set(declared_source_list)
    outbound_texts: list[str] = []
    questions = job.get("questions")
    if not isinstance(questions, list) or any(not isinstance(item, str) for item in questions):
        errors.append("questions_invalid")
    else:
        outbound_texts.extend(questions)
    if not isinstance(receipts, list):
        errors.append("receipts_invalid")
        receipts = []
    receipt_questions: list[str] = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            errors.append("receipt_invalid")
            continue
        if set(receipt) - ALLOWED_RECEIPT_FIELDS:
            errors.append("receipt_fields_forbidden")
        question = receipt.get("question")
        if isinstance(question, str):
            outbound_texts.append(question)
            receipt_questions.append(question)
            if isinstance(questions, list) and question not in questions:
                errors.append("receipt_question_not_declared")
        else:
            errors.append("receipt_question_invalid")
        if receipt.get("response_schema") != job.get("response_schema"):
            errors.append("receipt_response_schema_mismatch")
        chunks = receipt.get("chunks")
        if not isinstance(chunks, list):
            errors.append("receipt_chunks_invalid")
            chunks = []
        for chunk in chunks:
            if not isinstance(chunk, dict) or chunk.get("source_id") not in declared_sources:
                errors.append("receipt_source_not_declared")
                continue
            if set(chunk) - ALLOWED_CHUNK_FIELDS:
                errors.append("chunk_fields_forbidden")
            chunk_id = chunk.get("chunk_id")
            if not isinstance(chunk_id, str) or not chunk_id.startswith(
                f"{chunk['source_id']}:"
            ):
                errors.append("chunk_id_invalid")
            char_start = chunk.get("char_start")
            char_end = chunk.get("char_end")
            line_start = chunk.get("line_start")
            line_end = chunk.get("line_end")
            if (
                isinstance(char_start, bool)
                or not isinstance(char_start, int)
                or isinstance(char_end, bool)
                or not isinstance(char_end, int)
                or not 0 <= char_start <= char_end
            ):
                errors.append("chunk_character_range_invalid")
            if (
                isinstance(line_start, bool)
                or not isinstance(line_start, int)
                or isinstance(line_end, bool)
                or not isinstance(line_end, int)
                or not 1 <= line_start <= line_end
            ):
                errors.append("chunk_line_range_invalid")
            page_start = chunk.get("page_start")
            page_end = chunk.get("page_end")
            if (page_start is None) != (page_end is None) or (
                page_start is not None
                and (
                    isinstance(page_start, bool)
                    or not isinstance(page_start, int)
                    or isinstance(page_end, bool)
                    or not isinstance(page_end, int)
                    or not 1 <= page_start <= page_end
                )
            ):
                errors.append("chunk_page_range_invalid")
            text = chunk.get("text")
            if isinstance(text, str):
                outbound_texts.append(text)
            else:
                errors.append("receipt_text_invalid")
    if isinstance(questions, list) and receipt_questions != questions:
        errors.append("receipt_question_set_mismatch")
    for category in sorted(
        {category for text in outbound_texts for category in detect_sensitive_categories(text)}
    ):
        errors.append(f"sensitive_data_detected:{category}")
    unique_errors = tuple(dict.fromkeys(errors))
    return PackageValidation(not unique_errors, run_id, unique_errors)
