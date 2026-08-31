from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import ActionMode, JobEnvelope, PrivacyMode, SourceRecord, to_primitive

JOB_SCHEMA = "nemofold.job.v1"
JOB_SNAPSHOT_SCHEMA = "nemofold.job-snapshot.v1"
SUPPORTED_WORKFLOWS = frozenset(
    {
        "smart_inbox",
        "storage_policy",
        "cleanup_rules",
        "mail_to_case",
        "controlled_email",
        "contact_monitor",
        "bundle_export",
        "folder_digest",
        "evidence_analyst",
        "version_resolver",
        "report_studio",
        "platform_proof",
    }
)
ANALYSIS_WORKFLOWS = frozenset({"evidence_analyst", "platform_proof"})
ALLOWED_FIELDS = frozenset(
    {
        "schema",
        "workflow",
        "input_roots",
        "target_roots",
        "output_dir",
        "questions",
        "privacy_mode",
        "action_mode",
        "model_id",
        "model_budget_usd",
        "resume_run_id",
        "parameters",
    }
)
WORKFLOW_PARAMETER_FIELDS = {
    "smart_inbox": frozenset(
        {
            "allowed_extensions",
            "allowed_types",
            "classification_policy",
            "confidence_threshold",
            "naming_template",
            "original_policy",
            "retention_action",
            "retention_rule",
            "routes",
        }
    ),
    "storage_policy": frozenset(
        {
            "allowed_extensions",
            "allowed_types",
            "conversion_target",
            "naming_template",
            "original_policy",
            "retention_action",
            "retention_rule",
        }
    ),
    "cleanup_rules": frozenset(
        {
            "allowed_extensions",
            "corrections",
            "min_support",
            "naming_template",
            "original_policy",
            "retention_action",
            "rules",
        }
    ),
    "mail_to_case": frozenset({"case_id", "case_title", "include_attachments"}),
    "controlled_email": frozenset(
        {
            "attachment_source_ids",
            "body",
            "cc",
            "confirmation_digest",
            "from_address",
            "send_requested",
            "subject",
            "to",
        }
    ),
    "contact_monitor": frozenset({"contact_since_run_id"}),
    "bundle_export": frozenset(
        {"bundle_format", "bundle_name", "include_manifest", "order", "recursive"}
    ),
    "folder_digest": frozenset({"digest_depth", "since_run_id", "summary_length"}),
    "evidence_analyst": frozenset(
        {
            "analysis_mode",
            "citation_granularity",
            "conflict_scan",
            "formats",
            "max_chunks",
            "pseudonymize_terms",
            "title",
        }
    ),
    "version_resolver": frozenset(
        {"as_of", "fallback_to_file_time", "family_hint", "validity_fields"}
    ),
    "report_studio": frozenset({"formats", "include_coverage", "language", "template"}),
    "platform_proof": frozenset(
        {
            "analysis_mode",
            "citation_granularity",
            "conflict_scan",
            "evidence_level",
            "formats",
            "max_chunks",
            "network_gate",
            "pseudonymize_terms",
            "runtime",
            "title",
        }
    ),
}


def validate_workflow_parameters(job: JobEnvelope) -> None:
    allowed = WORKFLOW_PARAMETER_FIELDS.get(job.workflow)
    if allowed is None:
        raise ValueError(f"unsupported workflow: {job.workflow}")
    unknown = sorted(set(job.parameters) - allowed)
    if unknown:
        raise ValueError(f"unknown {job.workflow} parameter: {unknown[0]}")

    def choice(name: str, supported: set[object]) -> None:
        if name in job.parameters and job.parameters[name] not in supported:
            raise ValueError(f"unsupported {name}: {job.parameters[name]}")

    if job.workflow == "smart_inbox":
        choice("classification_policy", {"suffix_routes"})
        threshold = job.parameters.get("confidence_threshold", 1.0)
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not 0 <= threshold <= 1
        ):
            raise ValueError("confidence_threshold must be between 0 and 1")
    elif job.workflow == "cleanup_rules":
        minimum = job.parameters.get("min_support", 2)
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
            raise ValueError("min_support must be a positive integer")
        for name in ("rules", "corrections"):
            value = job.parameters.get(name, [])
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise ValueError(f"{name} must be a list of objects")
        seen_cleanup_suffixes: set[str] = set()
        for rule in job.parameters.get("rules", []):
            if set(rule) != {"suffixes", "target_root"}:
                raise ValueError("cleanup rule must contain only suffixes and target_root")
            if not isinstance(rule["suffixes"], list) or any(
                not isinstance(item, str) or not item.strip() for item in rule["suffixes"]
            ):
                raise ValueError("cleanup rule suffixes must be non-empty strings")
            if isinstance(rule["target_root"], bool) or not isinstance(
                rule["target_root"], int
            ):
                raise ValueError("cleanup rule target_root must be an integer")
            normalized = {
                item.casefold() if item.startswith(".") else f".{item.casefold()}"
                for item in rule["suffixes"]
            }
            if seen_cleanup_suffixes & normalized:
                raise ValueError("cleanup rule suffixes must not overlap")
            seen_cleanup_suffixes.update(normalized)
        for correction in job.parameters.get("corrections", []):
            if set(correction) != {"source", "target_root"}:
                raise ValueError("cleanup correction must contain only source and target_root")
    elif job.workflow == "mail_to_case":
        for name in ("case_id", "case_title"):
            value = job.parameters.get(name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string")
        if "include_attachments" in job.parameters and not isinstance(
            job.parameters["include_attachments"], bool
        ):
            raise ValueError("include_attachments must be a boolean")
    elif job.workflow == "controlled_email":
        for name in ("to", "cc", "attachment_source_ids"):
            value = job.parameters.get(name, [])
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                raise ValueError(f"{name} must be a list of non-empty strings")
        for name in ("from_address", "subject", "body", "confirmation_digest"):
            value = job.parameters.get(name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} must be a string")
        if "send_requested" in job.parameters and not isinstance(
            job.parameters["send_requested"], bool
        ):
            raise ValueError("send_requested must be a boolean")
    elif job.workflow == "contact_monitor":
        since_run_id = job.parameters.get("contact_since_run_id")
        if since_run_id is not None and (
            not isinstance(since_run_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", since_run_id)
        ):
            raise ValueError("since_run_id contains unsafe characters")
    elif job.workflow == "bundle_export":
        choice("bundle_format", {"text"})
        choice("order", {"display_name"})
        choice("recursive", {True})
        choice("include_manifest", {True})
    elif job.workflow == "folder_digest":
        choice("digest_depth", {"full"})
    elif job.workflow in {"evidence_analyst", "platform_proof"}:
        choice("analysis_mode", {"local_extractive", "nemotron"})
        choice("citation_granularity", {"line_or_page"})
        if job.parameters.get("analysis_mode") == "nemotron" and not job.model_id:
            raise ValueError("nemotron analysis_mode requires model_id")
    elif job.workflow == "report_studio":
        choice("template", {"default"})
        choice("language", {"en"})
        choice("include_coverage", {True})
    if job.workflow == "platform_proof":
        choice("runtime", {"nemoclaw", "offline"})
        choice("network_gate", {"approved", "closed"})
        choice("evidence_level", {"live", "offline"})
        if job.parameters.get("evidence_level") == "live" and not job.model_id:
            raise ValueError("live evidence_level requires model_id")


class JobFileError(ValueError):
    """Raised when a job file fails the public fail-closed contract."""


@dataclass(frozen=True, slots=True)
class LoadedJob:
    job: JobEnvelope
    source_path: Path


def _string_list(value: Any, field_name: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise JobFileError(f"{field_name} must be a list of strings")
    normalized = tuple(item.strip() for item in value)
    if any(not item for item in normalized) or (required and not normalized):
        raise JobFileError(f"{field_name} must contain non-empty values")
    return normalized


def _resolve_paths(values: tuple[str, ...], base: Path) -> tuple[str, ...]:
    return tuple(
        str((Path(item) if Path(item).is_absolute() else base / item).resolve())
        for item in values
    )


def parse_job_payload(payload: Any, *, base_dir: str | Path) -> JobEnvelope:
    if not isinstance(payload, dict):
        raise JobFileError("job file root must be an object")

    unknown = sorted(set(payload) - ALLOWED_FIELDS)
    if unknown:
        raise JobFileError(f"unknown fields: {', '.join(unknown)}")
    if payload.get("schema") != JOB_SCHEMA:
        raise JobFileError(f"schema must be {JOB_SCHEMA}")
    workflow = payload.get("workflow")
    if not isinstance(workflow, str) or workflow not in SUPPORTED_WORKFLOWS:
        raise JobFileError("workflow is not supported")

    input_roots = _string_list(payload.get("input_roots"), "input_roots", required=True)
    target_roots = _string_list(payload.get("target_roots", []), "target_roots")
    questions = _string_list(payload.get("questions", []), "questions")
    if workflow in ANALYSIS_WORKFLOWS and not questions:
        raise JobFileError("questions are required for analysis workflows")

    output_dir = payload.get("output_dir")
    if not isinstance(output_dir, str) or not output_dir.strip():
        raise JobFileError("output_dir must be a non-empty path")
    base = Path(base_dir).resolve()
    resolved_output = Path(output_dir)
    if not resolved_output.is_absolute():
        resolved_output = base / resolved_output

    try:
        privacy_mode = PrivacyMode(payload.get("privacy_mode", PrivacyMode.LOCAL_ONLY))
    except ValueError as exc:
        raise JobFileError("privacy_mode is invalid") from exc
    try:
        action_mode = ActionMode(payload.get("action_mode", ActionMode.DRY_RUN))
    except ValueError as exc:
        raise JobFileError("action_mode is invalid") from exc

    model_id = payload.get("model_id")
    if model_id is not None and (not isinstance(model_id, str) or not model_id.strip()):
        raise JobFileError("model_id must be null or a non-empty string")
    budget = payload.get("model_budget_usd", 0.0)
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget < 0:
        raise JobFileError("model_budget_usd must be a non-negative number")
    resume_run_id = payload.get("resume_run_id")
    if resume_run_id is not None and (
        not isinstance(resume_run_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]+", resume_run_id)
    ):
        raise JobFileError("resume_run_id contains unsafe characters")
    parameters = payload.get("parameters", {})
    if not isinstance(parameters, dict) or any(not isinstance(key, str) for key in parameters):
        raise JobFileError("parameters must be an object with string keys")

    job = JobEnvelope(
        workflow=workflow,
        input_roots=_resolve_paths(input_roots, base),
        target_roots=_resolve_paths(target_roots, base),
        output_dir=str(resolved_output.resolve()),
        questions=questions,
        privacy_mode=privacy_mode,
        action_mode=action_mode,
        model_id=model_id.strip() if isinstance(model_id, str) else None,
        model_budget_usd=float(budget),
        resume_run_id=resume_run_id,
        parameters=parameters,
    )
    try:
        validate_workflow_parameters(job)
    except ValueError as exc:
        raise JobFileError(str(exc)) from exc
    return job


def load_job_file(path: str | Path) -> LoadedJob:
    source_path = Path(path).resolve()
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise JobFileError(f"job file cannot be read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise JobFileError(f"job file is not valid JSON: {exc}") from exc
    return LoadedJob(
        job=parse_job_payload(payload, base_dir=source_path.parent),
        source_path=source_path,
    )


def job_snapshot_payload(job: JobEnvelope) -> dict[str, Any]:
    return {"schema": JOB_SNAPSHOT_SCHEMA, "job": to_primitive(job)}


def load_job_snapshot(path: str | Path) -> JobEnvelope:
    snapshot_path = Path(path).resolve()
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JobFileError(f"job snapshot cannot be read: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != JOB_SNAPSHOT_SCHEMA:
        raise JobFileError("job snapshot schema is invalid")
    value = payload.get("job")
    if not isinstance(value, dict):
        raise JobFileError("job snapshot payload is invalid")
    try:
        sources = tuple(
            SourceRecord(
                source_id=item["source_id"],
                path=item["path"],
                display_name=item["display_name"],
                sha256=item["sha256"],
                mime_type=item["mime_type"],
                extraction_status=item.get("extraction_status", "indexed"),
            )
            for item in value.get("sources", [])
        )
        job = JobEnvelope(
            workflow=value["workflow"],
            input_roots=tuple(value["input_roots"]),
            target_roots=tuple(value.get("target_roots", ())),
            output_dir=value["output_dir"],
            questions=tuple(value.get("questions", ())),
            privacy_mode=PrivacyMode(value.get("privacy_mode", "local_only")),
            action_mode=ActionMode(value.get("action_mode", "dry_run")),
            model_id=value.get("model_id"),
            model_budget_usd=float(value.get("model_budget_usd", 0.0)),
            sources=sources,
            response_schema=value.get("response_schema", "nemofold.claims.v1"),
            resume_run_id=value.get("resume_run_id"),
            parameters=dict(value.get("parameters", {})),
        )
        validate_workflow_parameters(job)
        return job
    except (KeyError, TypeError, ValueError) as exc:
        raise JobFileError(f"job snapshot contract is invalid: {exc}") from exc
