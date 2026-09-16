from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .contracts import ActionMode, JobEnvelope, PrivacyMode, SourceRecord, to_primitive
from .document_registry import columns_from_parameters
from .pdf_page_expectations import parse_pdf_page_reviews, parse_source_page_reviews

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
        "document_registry",
        "fact_distill",
        "synopsis_merge",
        "daily_arrivals",
        "person_registry",
        "relation_model",
        "person_timeline",
        "coverage_timeline",
        "alibi_weave",
        "contradiction_synopsis",
        "corpus_query",
        "web_research",
        "dossier",
        "bundle_completeness_check",
        "print_action",
        "reference_check",
        "rater_race",
        "guide_compose",
        "wiki_export",
        "pattern_mining",
        "document_compose",
        "mail_merge_compose",
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
    # Case Chronicle. Every vocabulary a caller can widen - names, places,
    # contested terms - is a declared parameter rather than a heuristic, so the
    # workflow can be told about a corpus instead of guessing at one.
    "person_registry": frozenset(
        {
        "source_tables",
        "structured_sources",
        "formats", "known_names", "match_surnames", "name_fields", "title"}
    ),
    "relation_model": frozenset(
        {
        "source_tables",
        "structured_sources",
        "formats", "known_names", "match_surnames", "name_fields", "pseudonymous", "title"}
    ),
    "person_timeline": frozenset(
        {
        "source_tables",
        "structured_sources",
        "formats", "known_names", "match_surnames", "name_fields", "title"}
    ),
    "coverage_timeline": frozenset(
        {
        "source_tables",
        "structured_sources",
        "end_field", "formats", "holder_field", "label_field", "start_field", "title"}
    ),
    "alibi_weave": frozenset(
        {
        "source_tables",
        "structured_sources",
            "formats", "known_names", "match_surnames", "name_fields", "places", "title",
            "tolerance_minutes", "window",
        }
    ),
    "contradiction_synopsis": frozenset({
        "source_tables",
        "structured_sources",
        "contested_terms", "formats", "title"}),
    "corpus_query": frozenset(
        {
        "source_tables",
        "structured_sources",
        "dedupe_scope", "formats", "max_per_source", "max_results", "partition_size",
         "terms", "title"}
    ),
    # The web contracts take no source_tables: they read no folder at all.
    "web_research": frozenset({"formats", "max_results", "queries", "title", "web_adapter"}),
    "dossier": frozenset(
        {"formats", "max_results", "queries", "subject", "title", "web_adapter"}
    ),
    "bundle_completeness_check": frozenset(
        {"formats", "required_formats", "required_parts", "title"}
    ),
    "reference_check": frozenset(
        {"formats", "reference_grid", "reference_items", "require_complete", "title"}
    ),
    "rater_race": frozenset(
        {"coding_scheme", "formats", "rater_a", "rater_b", "scan_labels", "title"}
    ),
    "guide_compose": frozenset({"dedupe_scope", "formats", "title"}),
    "wiki_export": frozenset({"formats", "title", "wiki_dir"}),
    "pattern_mining": frozenset(
        {"focus_terms", "formats", "max_patterns", "min_support", "partition_size",
         "title"}
    ),
    "document_compose": frozenset(
        {"basename", "fields", "formats", "template_path", "title"}
    ),
    "mail_merge_compose": frozenset(
        {"basename", "contact_book", "fields", "formats", "template_path", "title"}
    ),
    "print_action": frozenset({"formats", "source_id", "title"}),
    "mail_to_case": frozenset({"case_id", "case_title", "include_attachments"}),
    "controlled_email": frozenset(
        {
            "contact_book",
            "recipient_class_rights",
            "rights",
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
        {
        "source_tables",
        "structured_sources",
        "bundle_format", "bundle_name", "include_manifest", "order", "recursive"}
    ),
    "folder_digest": frozenset({
        "source_tables",
        "structured_sources",
        "digest_depth", "since_run_id", "summary_length"}),
    "evidence_analyst": frozenset(
        {
        "source_tables",
        "structured_sources",
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
    "synopsis_merge": frozenset({
        "application_domain",
        "medical_purpose",
        "source_tables",
        "structured_sources",
        "source_selected_lines",
        "formats", "title"}),
    "daily_arrivals": frozenset(
        {
            "export_task_snippet",
            "formats",
            # The baseline is named explicitly, exactly as folder_digest does it:
            # "new since some snapshot the caller picked" is a fact, "new since
            # whatever ran last" would be a guess about the caller's intent.
            "since_run_id",
            "summary_length",
            "task_run_at",
            "title",
        }
    ),
    "fact_distill": frozenset(
        {
            "delivery_policy",
        "source_tables",
        "structured_sources",
        "dedupe_scope", "focus_terms", "formats", "max_facts_per_source", "title"}
    ),
    "document_registry": frozenset(
        {
            "required_columns",
            "expected_pdf_pages",
            "pdf_page_reviews",
            "require_complete_pdf_inventory",
            "source_tables",
            "structured_sources",
            "column_template",
            "columns",
            "due_column",
            "due_within_days",
            "formats",
            "reference_date",
            "title",
            "topic_filter",
        }
    ),
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
    if "source_tables" in job.parameters:
        tables = job.parameters["source_tables"]
        if not isinstance(tables, list) or len(tables) > 64:
            raise ValueError("source_tables must be a list of at most 64 names")
        if any(
            not isinstance(name, str)
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", name) is None
            for name in tables
        ):
            raise ValueError("source_tables contains an invalid table name")
        if len(set(tables)) != len(tables):
            raise ValueError("source_tables must not repeat a table name")
    if "structured_sources" in job.parameters and not isinstance(
        job.parameters["structured_sources"], bool
    ):
        raise ValueError("structured_sources must be a boolean")
    if "expected_pdf_pages" in job.parameters:
        expectations = job.parameters["expected_pdf_pages"]
        if not isinstance(expectations, dict) or len(expectations) > 500:
            raise ValueError("expected_pdf_pages must be a bounded source map")
        normalized_names: set[str] = set()
        for name, count in expectations.items():
            if (
                not isinstance(name, str)
                or not name
                or len(name) > 240
                or "\\" in name
                or ":" in name
                or not name.casefold().endswith(".pdf")
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or name.casefold() in normalized_names
                or isinstance(count, bool)
                or not isinstance(count, int)
                or not 1 <= count <= 10000
            ):
                raise ValueError("expected_pdf_pages contains an invalid source or count")
            normalized_names.add(name.casefold())
    if "require_complete_pdf_inventory" in job.parameters and not isinstance(
        job.parameters["require_complete_pdf_inventory"], bool
    ):
        raise ValueError("require_complete_pdf_inventory must be a boolean")
    if "pdf_page_reviews" in job.parameters:
        reviews = parse_pdf_page_reviews(job.parameters["pdf_page_reviews"])
        expectations = job.parameters.get("expected_pdf_pages", {})
        if not isinstance(expectations, dict) or set(reviews) - set(expectations):
            raise ValueError("pdf_page_reviews must name declared expected_pdf_pages")
    if "source_selected_lines" in job.parameters:
        selections = job.parameters["source_selected_lines"]
        if not isinstance(selections, dict) or len(selections) > 500:
            raise ValueError("source_selected_lines must be a bounded source map")
        for source_id, lines in selections.items():
            if (
                not isinstance(source_id, str)
                or not source_id
                or not isinstance(lines, list)
                or not lines
                or len(lines) > 128000
                or any(isinstance(number, bool) or not isinstance(number, int)
                       or number < 1 or number > 500000 for number in lines)
                or lines != sorted(set(lines))
            ):
                raise ValueError("source_selected_lines contains an invalid selection")

    def choice(name: str, supported: set[object]) -> None:
        if name not in job.parameters:
            return
        value = job.parameters[name]
        if not any(type(value) is type(option) and value == option for option in supported):
            raise ValueError(f"unsupported {name}: {value}")

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
    elif job.workflow == "daily_arrivals":
        length = job.parameters.get("summary_length", 3)
        if isinstance(length, bool) or not isinstance(length, int) or not 1 <= length <= 20:
            raise ValueError("summary_length must be between 1 and 20")
        if "export_task_snippet" in job.parameters and not isinstance(
            job.parameters["export_task_snippet"], bool
        ):
            raise ValueError("export_task_snippet must be a boolean")
        run_at = job.parameters.get("task_run_at", "07:00:00")
        if not isinstance(run_at, str) or not re.fullmatch(r"\d{2}:\d{2}:\d{2}", run_at):
            raise ValueError("task_run_at must look like HH:MM:SS")
    elif job.workflow == "fact_distill":
        choice("dedupe_scope", {"exact", "normalized"})
        focus = job.parameters.get("focus_terms", [])
        if not isinstance(focus, list) or any(
            not isinstance(item, str) or not item.strip() for item in focus
        ):
            raise ValueError("focus_terms must be a list of non-empty strings")
        limit = job.parameters.get("max_facts_per_source", 200)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2000:
            raise ValueError("max_facts_per_source must be between 1 and 2000")
    elif job.workflow == "document_registry":
        # The column contract itself is validated in document_registry; here only
        # the job-level shape is checked, so an unusable job fails before a run.
        columns_from_parameters(
            job.parameters.get("columns"), job.parameters.get("column_template")
        )
        topic_filter = job.parameters.get("topic_filter", [])
        if not isinstance(topic_filter, list) or any(
            not isinstance(item, str) or not item.strip() for item in topic_filter
        ):
            raise ValueError("topic_filter must be a list of non-empty strings")
        due_column = job.parameters.get("due_column")
        if due_column is not None and (
            not isinstance(due_column, str) or not due_column.strip()
        ):
            raise ValueError("due_column must be a non-empty string")
        window = job.parameters.get("due_within_days", 30)
        if isinstance(window, bool) or not isinstance(window, int) or not 0 <= window <= 3660:
            raise ValueError("due_within_days must be between 0 and 3660")
        reference = job.parameters.get("reference_date")
        if reference is not None:
            if not isinstance(reference, str):
                raise ValueError("reference_date must be an ISO date string")
            try:
                date.fromisoformat(reference)
            except ValueError as exc:
                raise ValueError("reference_date must be an ISO date string") from exc
    elif job.workflow == "synopsis_merge":
        if "application_domain" not in job.parameters:
            raise ValueError("application_domain is required for synopsis_merge")
        choice("application_domain", {"general_documents", "medical_reports"})
        choice(
            "medical_purpose",
            {
                "source_summary",
                "diagnosis",
                "treatment_recommendation",
                "urgency_assessment",
            },
        )
        if (
            "medical_purpose" in job.parameters
            and job.parameters.get("application_domain") != "medical_reports"
        ):
            raise ValueError(
                "medical_purpose requires application_domain=medical_reports"
            )
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


HANDOFF_CONTEXT_SCHEMA = "nemofold.selected-source-handoff.v1"


def validate_handoff_context(job: JobEnvelope) -> None:
    """Validate internal receipt-bound data that public job files cannot set."""
    context = job.handoff_context
    if not isinstance(context, dict):
        raise ValueError("handoff_context must be an object")
    if not context:
        return
    if set(context) != {"schema", "source_page_reviews", "reviewed_page_receipts"}:
        raise ValueError("handoff_context fields are invalid")
    if context.get("schema") != HANDOFF_CONTEXT_SCHEMA:
        raise ValueError("handoff_context schema is invalid")
    reviews = parse_source_page_reviews(context.get("source_page_reviews"))
    expected_receipts = {
        source_id: [review.as_summary() for review in source_reviews]
        for source_id, source_reviews in reviews.items()
    }
    if context.get("reviewed_page_receipts") != expected_receipts:
        raise ValueError("handoff_context review receipts do not match")


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
            handoff_context=dict(value.get("handoff_context", {})),
        )
        validate_workflow_parameters(job)
        validate_handoff_context(job)
        return job
    except (KeyError, TypeError, ValueError) as exc:
        raise JobFileError(f"job snapshot contract is invalid: {exc}") from exc
