from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from .anonymizer import (
    detect_sensitive_categories,
    pseudonymize_questions_and_receipts,
    pseudonymize_text,
)
from .application import ExecutionConfig, JobCommandResult
from .artifacts import write_text_artifact
from .contracts import (
    ActionMode,
    ArtifactRecord,
    Claim,
    EvidenceLocator,
    GateDecision,
    JobEnvelope,
    PrivacyMode,
    RunReport,
    RunStatus,
    to_primitive,
)
from .document_extract import extract_document_text
from .document_index import DocumentIndex, SearchHit
from .evidence import compute_coverage, validate_claim
from .evidence_analyst import ContextReceipt, build_context_receipts
from .inventory import InventoryResult, scan_paths
from .job_io import job_snapshot_payload, validate_workflow_parameters
from .ledger import RunLedger, validate_run_id
from .policy import PolicyConfig, PolicyGate
from .providers import ProviderAdapter, ProviderConfig, ProviderRequest, create_provider
from .report_studio import ReportDocument, render_report_formats

PROVIDER_ANALYSIS_SCHEMA = "nemofold.provider-analysis.v1"
PROVIDER_CONTEXT_SCHEMA = "nemofold.provider-context.v1"

PROVIDER_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "question_id": {"type": "string"},
                    "statement": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "source_id": {"type": "string"},
                                "quote": {"type": "string"},
                            },
                            "required": ["source_id", "quote"],
                        },
                    },
                    "uncertainty": {"type": "number", "minimum": 0, "maximum": 1},
                    "conflict_status": {
                        "type": "string",
                        "enum": [
                            "confirmed_conflict",
                            "none",
                            "potential_conflict",
                            "unverified",
                        ],
                    },
                },
                "required": [
                    "question_id",
                    "statement",
                    "evidence",
                    "uncertainty",
                    "conflict_status",
                ],
            },
        },
        "unanswered_question_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["answers", "unanswered_question_ids"],
}


def _provider_gate(
    job: JobEnvelope,
    execution: ExecutionConfig,
    provider: ProviderConfig,
    *,
    approve_external_transfer: bool,
) -> GateDecision:
    local_gate = PolicyGate(
        PolicyConfig(
            allowed_roots=execution.allowed_roots,
            apply_actions_allowed=execution.apply_actions_allowed,
        )
    ).evaluate(job)
    reasons = list(local_gate.reasons)
    descriptor = provider.descriptor
    if job.workflow != "evidence_analyst":
        reasons.append("provider_analysis_requires_evidence_analyst")
    if job.model_id is not None:
        reasons.append("generic_provider_job_must_not_declare_model_id")
    if job.action_mode is not ActionMode.DRY_RUN:
        reasons.append("provider_analysis_is_read_only")
    if descriptor.external_transfer:
        if not execution.external_models_allowed:
            reasons.append("external_models_disabled")
        if not approve_external_transfer:
            reasons.append("external_transfer_not_approved")
        if job.privacy_mode is not PrivacyMode.ALLOW_ONCE:
            reasons.append("external_privacy_not_approved")
        if descriptor.transport.value == "provider_api":
            if job.model_budget_usd <= 0:
                reasons.append("external_budget_missing")
            elif job.model_budget_usd > execution.max_external_cost_usd:
                reasons.append("external_budget_exceeds_limit")
    elif job.privacy_mode is not PrivacyMode.LOCAL_ONLY:
        reasons.append("local_provider_requires_local_only_privacy")
    return GateDecision(
        allowed=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        allowed_fields=("questions", "source_ids", "sanitized_context", "response_schema"),
        recipient=provider.provider_id,
        max_cost_usd=(
            min(job.model_budget_usd, execution.max_external_cost_usd)
            if descriptor.external_transfer
            else 0.0
        ),
    )


def _read_text_sources(inventory: InventoryResult) -> dict[str, str]:
    texts: dict[str, str] = {}
    for source in inventory.records:
        if source.extraction_status in {"unreadable", "excluded_symlink"}:
            continue
        try:
            texts[source.source_id] = extract_document_text(
                source.path,
                mime_type=source.mime_type,
            )
        except (OSError, UnicodeError, ValueError):
            continue
    return texts


def _provider_identity(job: JobEnvelope, provider: ProviderConfig) -> str:
    value = {
        "job": to_primitive(job),
        "provider": provider.public_summary(),
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"job_{hashlib.sha256(encoded).hexdigest()}"


def _json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("provider output is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("provider output root must be an object")
    return payload


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _response_schema(question_count: int) -> dict[str, Any]:
    question_ids = [f"q_{index:03d}" for index in range(1, question_count + 1)]
    schema = copy.deepcopy(PROVIDER_RESPONSE_SCHEMA)
    answers = schema["properties"]["answers"]
    answers["maxItems"] = question_count
    answers["items"]["properties"]["question_id"]["enum"] = question_ids
    unanswered = schema["properties"]["unanswered_question_ids"]
    unanswered["maxItems"] = question_count
    unanswered["items"]["enum"] = question_ids
    return schema


def _matching_hit(
    quote: str,
    source_id: str,
    receipt: ContextReceipt,
) -> SearchHit | None:
    normalized_quote = _normalized(quote)
    if not normalized_quote:
        return None
    return next(
        (
            hit
            for hit in receipt.hits
            if hit.source_id == source_id and normalized_quote in _normalized(hit.text)
        ),
        None,
    )


def _validated_claims(
    payload: dict[str, Any],
    *,
    receipts: tuple[ContextReceipt, ...],
    sensitive_terms: tuple[str, ...],
) -> tuple[tuple[Claim, ...], tuple[str, ...]]:
    if set(payload) != {"answers", "unanswered_question_ids"}:
        raise ValueError("provider output fields do not match the response contract")
    answers = payload.get("answers")
    unanswered = payload.get("unanswered_question_ids")
    if not isinstance(answers, list) or not isinstance(unanswered, list):
        raise ValueError("provider output answer collections are invalid")
    question_ids = tuple(f"q_{index:03d}" for index in range(1, len(receipts) + 1))
    receipt_by_id = dict(zip(question_ids, receipts, strict=True))
    seen: set[str] = set()
    claims: list[Claim] = []
    for answer in answers:
        required = {
            "question_id",
            "statement",
            "evidence",
            "uncertainty",
            "conflict_status",
        }
        if not isinstance(answer, dict) or set(answer) != required:
            raise ValueError("provider answer fields are invalid")
        question_id = answer["question_id"]
        if not isinstance(question_id, str) or question_id not in receipt_by_id:
            raise ValueError("provider answer references an unknown question")
        if question_id in seen:
            raise ValueError("provider answered a question more than once")
        statement = answer["statement"]
        evidence = answer["evidence"]
        if not isinstance(statement, str) or not isinstance(evidence, list) or not evidence:
            raise ValueError("provider answer must contain a statement and evidence")
        uncertainty = answer["uncertainty"]
        if isinstance(uncertainty, bool) or not isinstance(uncertainty, (int, float)):
            raise ValueError("provider answer uncertainty must be a number")
        conflict_status = answer["conflict_status"]
        if not isinstance(conflict_status, str):
            raise ValueError("provider answer conflict_status must be a string")
        locators: list[EvidenceLocator] = []
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {"source_id", "quote"}:
                raise ValueError("provider evidence fields are invalid")
            source_id = item["source_id"]
            quote = item["quote"]
            if not isinstance(source_id, str) or not isinstance(quote, str):
                raise ValueError("provider evidence values are invalid")
            hit = _matching_hit(quote, source_id, receipt_by_id[question_id])
            if hit is None:
                raise ValueError("provider evidence quote is not in the outbound context")
            locators.append(
                EvidenceLocator(
                    source_id=source_id,
                    quote=quote,
                    page=hit.page_start,
                    section=f"lines {hit.line_start}-{hit.line_end}",
                )
            )
        sanitized_statement = pseudonymize_text(
            statement,
            sensitive_terms=sensitive_terms,
        ).text
        claim = Claim(
            statement=sanitized_statement,
            evidence=tuple(locators),
            uncertainty=float(uncertainty),
            conflict_status=conflict_status,
        )
        allowed_text = {
            source_id: "\n".join(
                hit.text for hit in receipt_by_id[question_id].hits if hit.source_id == source_id
            )
            for source_id in {locator.source_id for locator in claim.evidence}
        }
        if not validate_claim(claim, allowed_text).verified:
            raise ValueError("provider claim did not pass the evidence validator")
        claims.append(claim)
        seen.add(question_id)
    if any(not isinstance(item, str) or item not in receipt_by_id for item in unanswered):
        raise ValueError("provider returned an unknown unanswered question")
    unanswered_ids = tuple(unanswered)
    if len(set(unanswered_ids)) != len(unanswered_ids) or seen & set(unanswered_ids):
        raise ValueError("provider question accounting overlaps or contains duplicates")
    if seen | set(unanswered_ids) != set(question_ids):
        raise ValueError("provider did not account for every question")
    return tuple(claims), unanswered_ids


def _prepare_context(
    job: JobEnvelope,
    inventory: InventoryResult,
) -> tuple[
    dict[str, str],
    tuple[ContextReceipt, ...],
    dict[str, Any],
    tuple[str, ...],
]:
    texts = _read_text_sources(inventory)
    max_chunks = job.parameters.get("max_chunks", 8)
    if isinstance(max_chunks, bool) or not isinstance(max_chunks, int) or max_chunks < 1:
        raise ValueError("max_chunks must be a positive integer")
    index = DocumentIndex(Path(job.output_dir) / "index" / "nemofold.sqlite3")
    try:
        index.prune_sources(frozenset(texts))
        for source in inventory.records:
            text = texts.get(source.source_id)
            if text is not None:
                index.index_source(source, text)
        receipts = build_context_receipts(index, job.questions, hits_per_question=max_chunks)
    finally:
        index.close()
    terms = job.parameters.get("pseudonymize_terms", [])
    if not isinstance(terms, list) or any(not isinstance(item, str) for item in terms):
        raise ValueError("pseudonymize_terms must be a list of strings")
    sensitive_terms = tuple(terms)
    sanitized = pseudonymize_questions_and_receipts(
        job.questions,
        receipts,
        sensitive_terms=sensitive_terms,
    )
    questions = [
        {"question_id": f"q_{question_index:03d}", "text": question}
        for question_index, question in enumerate(sanitized.questions, start=1)
    ]
    receipt_values = []
    for question_index, receipt in enumerate(sanitized.receipts, start=1):
        value = receipt.to_payload()
        receipt_values.append(
            {
                "question_id": f"q_{question_index:03d}",
                "chunks": value["chunks"],
            }
        )
    context = {
        "schema": PROVIDER_CONTEXT_SCHEMA,
        "questions": questions,
        "receipts": receipt_values,
        "response_schema": PROVIDER_ANALYSIS_SCHEMA,
    }
    outbound = json.dumps(context, indent=2, sort_keys=True)
    categories = detect_sensitive_categories(outbound)
    if categories:
        raise ValueError(f"sanitized context still contains: {', '.join(categories)}")
    return texts, sanitized.receipts, context, sensitive_terms


def analyze_with_provider(
    job: JobEnvelope,
    execution: ExecutionConfig,
    provider_config: ProviderConfig,
    *,
    run_id: str,
    approve_external_transfer: bool = False,
    adapter: ProviderAdapter | None = None,
) -> JobCommandResult:
    validate_run_id(run_id)
    validate_workflow_parameters(job)
    decision = _provider_gate(
        job,
        execution,
        provider_config,
        approve_external_transfer=approve_external_transfer,
    )
    identity = _provider_identity(job, provider_config)
    gate = PolicyGate(PolicyConfig(allowed_roots=execution.allowed_roots))
    if not decision.allowed:
        report = RunReport(
            run_id=run_id,
            idempotency_key=identity,
            workflow=job.workflow,
            status=RunStatus.BLOCKED,
            errors=decision.reasons,
            gate_decision=decision,
            metadata={
                "provider": provider_config.public_summary(),
                "provider_execution_proof": False,
                "competition_proof": False,
                "cloud_proof": False,
                "transfer_performed": False,
            },
        )
        if not gate.path_allowed(job.output_dir):
            return JobCommandResult(report, None)
        ledger = RunLedger(Path(job.output_dir) / "ledger")
        ledger.save(report)
        return JobCommandResult(report, Path(job.output_dir) / "ledger" / f"{run_id}.json")

    inventory = scan_paths(job.input_roots)
    prepared = replace(job, sources=inventory.records)
    identity = _provider_identity(prepared, provider_config)
    output = Path(prepared.output_dir)
    ledger = RunLedger(output / "ledger")
    try:
        existing = ledger.load(run_id)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if existing.idempotency_key != identity:
            raise ValueError("run_id already belongs to a different provider job")
        if existing.status is RunStatus.EXECUTED:
            return JobCommandResult(existing, output / "ledger" / f"{run_id}.json")
        raise ValueError("provider runs are not resumed implicitly; use a new run_id")

    write_text_artifact(
        output / "jobs" / f"{run_id}.json",
        json.dumps(
            {
                **job_snapshot_payload(prepared),
                "provider": provider_config.public_summary(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "provider-job-snapshot",
    )
    initial = RunReport(
        run_id=run_id,
        idempotency_key=identity,
        workflow=prepared.workflow,
        status=RunStatus.PLANNED,
        gate_decision=decision,
        metadata={
            "provider": provider_config.public_summary(),
            "provider_execution_proof": False,
            "competition_proof": False,
            "cloud_proof": False,
            "source_count": len(inventory.records),
            "transfer_performed": False,
        },
    )
    ledger.save(initial)
    running = ledger.transition(run_id, RunStatus.RUNNING)
    request_record: ArtifactRecord | None = None
    provider_attempted = False
    provider_returned = False
    raw_response_sha256: str | None = None
    try:
        texts, receipts, context, sensitive_terms = _prepare_context(prepared, inventory)
        context_text = json.dumps(context, indent=2, sort_keys=True) + "\n"
        system_prompt = (
            "You are NemoFold's evidence analyst. Answer only from the supplied chunks. "
            "Every quote must be copied exactly from a chunk belonging to the same "
            "question. Return at most one answer object per question_id; combine all "
            "evidence for one question in that object. Account for each question exactly "
            "once, either in answers or unanswered_question_ids. Use source IDs only; "
            "never invent paths, names, or evidence. Do not call tools, inspect the "
            "filesystem, or access any network resource."
        )
        response_schema = _response_schema(len(receipts))
        provider_request = ProviderRequest(
            system_prompt=system_prompt,
            user_prompt=context_text,
            response_schema=response_schema,
        )
        request_payload = {
            "schema": "nemofold.provider-request.v1",
            "run_id": run_id,
            "provider": provider_config.public_summary(),
            "system_prompt": system_prompt,
            "context": context,
            "response_schema": response_schema,
            "transfer_performed": False,
            "competition_proof": False,
        }
        request_record = write_text_artifact(
            output / "provider-runs" / f"{run_id}.request.json",
            json.dumps(request_payload, indent=2, sort_keys=True) + "\n",
            "provider-request",
        )
        provider_attempted = True
        response = (adapter or create_provider(provider_config)).generate(provider_request)
        provider_returned = True
        if response.provider_id != provider_config.provider_id:
            raise ValueError("provider response identity does not match the selected provider")
        if not isinstance(response.model, str) or not response.model.strip():
            raise ValueError("provider response model must not be blank")
        raw_response_sha256 = hashlib.sha256(response.text.encode()).hexdigest()
        response_payload = _json_object(response.text)
        claims, unanswered_ids = _validated_claims(
            response_payload,
            receipts=receipts,
            sensitive_terms=sensitive_terms,
        )
        cited_ids = {locator.source_id for claim in claims for locator in claim.evidence}
        coverage = compute_coverage(
            all_source_ids=(source.source_id for source in inventory.records),
            read_source_ids=texts,
            cited_source_ids=cited_ids,
        )
        transfer_performed = provider_config.descriptor.external_transfer
        result_payload = {
            "schema": PROVIDER_ANALYSIS_SCHEMA,
            "run_id": run_id,
            "provider": provider_config.public_summary(),
            "resolved_model": response.model,
            "request_id": response.request_id,
            "usage": response.usage,
            "request_artifact_sha256": request_record.sha256,
            "raw_response_sha256": raw_response_sha256,
            "answers": [to_primitive(claim) for claim in claims],
            "unanswered_questions": [
                prepared.questions[int(item.removeprefix("q_")) - 1] for item in unanswered_ids
            ],
            "coverage": to_primitive(coverage),
            "transfer_performed": transfer_performed,
            "provider_execution_proof": True,
            "cost_bound_enforced": False,
            "competition_proof": False,
            "cloud_proof": False,
        }
        result_record = write_text_artifact(
            output / "provider-runs" / f"{run_id}.result.json",
            json.dumps(result_payload, indent=2, sort_keys=True) + "\n",
            "provider-result",
        )
        formats = prepared.parameters.get("formats", ["md", "txt"])
        if not isinstance(formats, list) or any(not isinstance(item, str) for item in formats):
            raise ValueError("formats must be a list of strings")
        source_labels = tuple(
            (source.source_id, source.display_name) for source in inventory.records
        )
        report_records = render_report_formats(
            ReportDocument(
                title=str(prepared.parameters.get("title", "NemoFold provider analysis")),
                claims=claims,
                coverage=coverage,
                source_labels=source_labels,
            ),
            output,
            basename=f"{run_id}-provider",
            formats=tuple(formats),
        )
    except Exception as exc:
        external = provider_config.descriptor.external_transfer
        failure_transfer: bool | None = False
        if external and provider_attempted:
            failure_transfer = True if provider_returned else None
        failure_record = write_text_artifact(
            output / "provider-runs" / f"{run_id}.failure.json",
            json.dumps(
                {
                    "schema": "nemofold.provider-failure.v1",
                    "run_id": run_id,
                    "provider": provider_config.public_summary(),
                    "error": f"provider_error:{type(exc).__name__}",
                    "transfer_performed": failure_transfer,
                    "provider_execution_proof": False,
                    "request_artifact_sha256": (request_record.sha256 if request_record else None),
                    "raw_response_sha256": raw_response_sha256,
                    "cost_bound_enforced": False,
                    "competition_proof": False,
                    "cloud_proof": False,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "provider-failure",
        )
        artifacts = ((request_record,) if request_record else ()) + (failure_record,)
        failed = replace(
            running,
            status=RunStatus.FAILED,
            errors=(f"provider_error:{type(exc).__name__}",),
            artifacts=artifacts,
            metadata={
                **running.metadata,
                "transfer_performed": failure_transfer,
            },
        )
        ledger.update(failed)
        return JobCommandResult(failed, output / "ledger" / f"{run_id}.json")

    final = replace(
        running,
        status=RunStatus.EXECUTED,
        actions=(
            "inventory_scanned",
            "local_index_built",
            "context_pseudonymized",
            "provider_invoked",
            "provider_claims_validated",
            "reports_exported",
        ),
        errors=(),
        coverage=coverage,
        artifacts=(request_record, result_record) + report_records,
        metadata={
            **running.metadata,
            "resolved_model": response.model,
            "usage": response.usage,
            "answered_questions": len(claims),
            "unanswered_questions": [
                prepared.questions[int(item.removeprefix("q_")) - 1] for item in unanswered_ids
            ],
            "transfer_performed": transfer_performed,
            "provider_execution_proof": True,
            "competition_proof": False,
            "cloud_proof": False,
        },
    )
    ledger.update(final)
    return JobCommandResult(final, output / "ledger" / f"{run_id}.json")
