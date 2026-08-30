from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .anonymizer import detect_sensitive_categories
from .nemoclaw_package import TRANSFER_ATTEMPT_FILENAME, validate_job_package

RESULT_SCHEMA = "nemofold.live-result.v1"
TRANSFER_ATTEMPT_SCHEMA = "nemofold.transfer-attempt.v1"
MODEL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["answered", "insufficient_evidence"],
                    },
                    "claims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "statement": {"type": "string"},
                                "uncertainty": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "conflict_status": {
                                    "type": "string",
                                    "enum": [
                                        "confirmed_conflict",
                                        "none",
                                        "potential_conflict",
                                        "unverified",
                                    ],
                                },
                                "evidence": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "chunk_id": {"type": "string"},
                                            "source_id": {"type": "string"},
                                            "quote": {"type": "string"},
                                        },
                                        "required": ["chunk_id", "source_id", "quote"],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "required": [
                                "statement",
                                "uncertainty",
                                "conflict_status",
                                "evidence",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["question", "status", "claims"],
                "additionalProperties": False,
            },
        },
        "read_source_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["answers", "read_source_ids"],
    "additionalProperties": False,
}
TOKEN_FACTORY_SYSTEM_PROMPT = (
    "You are the isolated NemoFold evidence worker. Use only the supplied "
    "pseudonymized chunks. Answer each question once and in order. Every supported "
    "claim must cite an exact substring from one declared chunk, with the matching "
    "chunk_id and source_id. If the chunks do not support an answer, return "
    "insufficient_evidence with no claims. Never infer paths, identities, missing "
    "facts, or outside knowledge. Return only JSON matching the supplied schema."
)


@dataclass(frozen=True, slots=True)
class ResultValidation:
    valid: bool
    run_id: str | None
    status: str | None
    errors: tuple[str, ...]


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def expected_token_factory_request(
    job: dict[str, Any], receipts: list[Any], *, max_completion_tokens: int
) -> dict[str, Any]:
    model = job.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("id"), str):
        raise ValueError("NemoClaw package model declaration is invalid")
    task = {
        "run_id": job.get("run_id"),
        "questions": job.get("questions"),
        "context_receipts": receipts,
    }
    return {
        "model": model["id"],
        "messages": [
            {"role": "system", "content": TOKEN_FACTORY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(task, sort_keys=True, separators=(",", ":")),
            },
        ],
        "store": False,
        "max_completion_tokens": max_completion_tokens,
        "temperature": 0,
        "n": 1,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": MODEL_OUTPUT_SCHEMA,
        },
    }


def _unique(errors: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(errors))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _context_contract(
    job: dict[str, Any], receipts: list[Any]
) -> tuple[list[str], set[str], dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    questions = job.get("questions")
    if not isinstance(questions, list) or any(not isinstance(item, str) for item in questions):
        return [], set(), {}, ["questions_invalid"]
    sources_value = job.get("sources")
    if not isinstance(sources_value, list):
        return questions, set(), {}, ["sources_invalid"]
    source_ids: set[str] = set()
    for item in sources_value:
        if isinstance(item, dict) and isinstance(item.get("source_id"), str):
            source_ids.add(item["source_id"])
    chunks: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        if not isinstance(receipt, dict) or not isinstance(receipt.get("chunks"), list):
            errors.append("receipt_invalid")
            continue
        for chunk in receipt["chunks"]:
            if not isinstance(chunk, dict):
                errors.append("chunk_invalid")
                continue
            chunk_id = chunk.get("chunk_id")
            if not isinstance(chunk_id, str) or chunk_id in chunks:
                errors.append("chunk_id_invalid_or_duplicate")
                continue
            chunks[chunk_id] = chunk
    return questions, source_ids, chunks, errors


def validate_model_output(
    job: dict[str, Any], receipts: list[Any], output: Any
) -> tuple[str, ...]:
    errors: list[str] = []
    questions, source_ids, chunks, contract_errors = _context_contract(job, receipts)
    errors.extend(contract_errors)
    if not isinstance(output, dict) or set(output) != {"answers", "read_source_ids"}:
        return _unique(errors + ["model_output_contract_invalid"])
    answers = output.get("answers")
    if not isinstance(answers, list):
        errors.append("answers_invalid")
        answers = []
    answer_questions: list[str] = []
    for answer in answers:
        if not isinstance(answer, dict) or set(answer) != {"question", "status", "claims"}:
            errors.append("answer_contract_invalid")
            continue
        question = answer.get("question")
        if not isinstance(question, str):
            errors.append("answer_question_invalid")
        else:
            answer_questions.append(question)
        status = answer.get("status")
        if status not in {"answered", "insufficient_evidence"}:
            errors.append("answer_status_invalid")
        claims = answer.get("claims")
        if not isinstance(claims, list):
            errors.append("answer_claims_invalid")
            continue
        if status == "answered" and not claims:
            errors.append("answered_without_claims")
        if status == "insufficient_evidence" and claims:
            errors.append("insufficient_answer_has_claims")
        for claim in claims:
            required_claim_fields = {
                "statement",
                "uncertainty",
                "conflict_status",
                "evidence",
            }
            if not isinstance(claim, dict) or set(claim) != required_claim_fields:
                errors.append("claim_contract_invalid")
                continue
            if not isinstance(claim.get("statement"), str) or not claim["statement"].strip():
                errors.append("claim_statement_invalid")
            uncertainty = claim.get("uncertainty")
            if (
                isinstance(uncertainty, bool)
                or not isinstance(uncertainty, (int, float))
                or not math.isfinite(uncertainty)
                or not 0 <= uncertainty <= 1
            ):
                errors.append("claim_uncertainty_invalid")
            if claim.get("conflict_status") not in {
                "confirmed_conflict",
                "none",
                "potential_conflict",
                "unverified",
            }:
                errors.append("claim_conflict_status_invalid")
            evidence = claim.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                errors.append("claim_evidence_missing")
                continue
            for locator in evidence:
                if not isinstance(locator, dict) or set(locator) != {
                    "chunk_id",
                    "source_id",
                    "quote",
                }:
                    errors.append("locator_contract_invalid")
                    continue
                source_id = locator.get("source_id")
                chunk_id = locator.get("chunk_id")
                quote = locator.get("quote")
                chunk = chunks.get(chunk_id) if isinstance(chunk_id, str) else None
                if source_id not in source_ids or chunk is None:
                    errors.append("locator_reference_invalid")
                    continue
                if chunk.get("source_id") != source_id:
                    errors.append("locator_source_mismatch")
                chunk_text = chunk.get("text")
                if (
                    not isinstance(quote, str)
                    or not quote.strip()
                    or not isinstance(chunk_text, str)
                    or quote not in chunk_text
                ):
                    errors.append("locator_quote_invalid")
    if answer_questions != questions:
        errors.append("answer_question_set_mismatch")
    read_source_ids = output.get("read_source_ids")
    if (
        not isinstance(read_source_ids, list)
        or any(not isinstance(item, str) for item in read_source_ids)
        or len(set(read_source_ids)) != len(read_source_ids)
        or not set(read_source_ids).issubset(source_ids)
    ):
        errors.append("read_source_ids_invalid")
    return _unique(errors)


def _contains_forbidden_secret_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in {
                "api-key",
                "api_key",
                "authorization",
                "access_token",
            }:
                return True
            if _contains_forbidden_secret_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_secret_key(item) for item in value)
    return False


def _iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _provider_content(response_body: Any) -> Any:
    try:
        return json.loads(response_body["choices"][0]["message"]["content"])
    except (IndexError, KeyError, TypeError, json.JSONDecodeError):
        return None


def validate_result_package(path: str | Path) -> ResultValidation:
    package_path = Path(path)
    package_validation = validate_job_package(package_path)
    errors = [f"job_package:{item}" for item in package_validation.errors]
    result_path = package_path / "result.json"
    if not result_path.is_file() or result_path.is_symlink():
        return ResultValidation(False, package_validation.run_id, None, ("result_missing",))
    try:
        manifest = _load_json(package_path / "manifest.json")
        job = _load_json(package_path / "job.json")
        receipts = _load_json(package_path / "context-receipts.json")
        result = _load_json(result_path)
        attempt = _load_json(package_path / TRANSFER_ATTEMPT_FILENAME)
    except (OSError, json.JSONDecodeError):
        return ResultValidation(False, package_validation.run_id, None, ("result_json_invalid",))
    if (
        not isinstance(job, dict)
        or not isinstance(receipts, list)
        or not isinstance(result, dict)
        or not isinstance(attempt, dict)
    ):
        return ResultValidation(False, package_validation.run_id, None, ("result_inputs_invalid",))
    allowed_result_fields = {
        "cloud_proof",
        "errors",
        "model_id",
        "model_output",
        "provider",
        "provider_log",
        "response_schema",
        "run_id",
        "runtime_evidence",
        "schema",
        "status",
        "transfer_performed",
        "usage",
    }
    if set(result) != allowed_result_fields:
        errors.append("result_fields_invalid")
    run_id = result.get("run_id") if isinstance(result.get("run_id"), str) else None
    if run_id != manifest.get("run_id") or run_id != job.get("run_id"):
        errors.append("result_run_id_mismatch")
    if result.get("schema") != RESULT_SCHEMA:
        errors.append("result_schema_invalid")
    if result.get("response_schema") != job.get("response_schema"):
        errors.append("result_response_schema_mismatch")
    if result.get("provider") != "nebius-token-factory":
        errors.append("result_provider_invalid")
    model_value = job.get("model")
    model: dict[str, Any] = model_value if isinstance(model_value, dict) else {}
    if result.get("model_id") != model.get("id"):
        errors.append("result_model_mismatch")
    if result.get("transfer_performed") is not True:
        errors.append("result_transfer_not_proven")
    status = result.get("status") if isinstance(result.get("status"), str) else None
    result_errors = result.get("errors")
    if not isinstance(result_errors, list) or any(
        not isinstance(item, str) for item in result_errors
    ):
        errors.append("result_errors_invalid")
        result_errors = []
    if status == "executed":
        if result_errors:
            errors.append("executed_result_has_errors")
        errors.extend(validate_model_output(job, receipts, result.get("model_output")))
        if result.get("cloud_proof") is not True:
            errors.append("executed_result_missing_cloud_proof")
    elif status == "failed":
        if not result_errors:
            errors.append("failed_result_missing_errors")
        if result.get("cloud_proof") is not False:
            errors.append("failed_result_claims_cloud_proof")
    else:
        errors.append("result_status_invalid")

    usage = result.get("usage")
    usage_keys = {"completion_tokens", "prompt_tokens", "total_tokens"}
    usage_valid = True
    if not isinstance(usage, dict) or set(usage) != usage_keys:
        errors.append("usage_invalid")
        usage = {}
        usage_valid = False
    elif any(
        isinstance(usage.get(key), bool)
        or not isinstance(usage.get(key), int)
        or usage[key] < 0
        for key in usage_keys
    ):
        errors.append("usage_invalid")
        usage_valid = False
    elif usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]:
        errors.append("usage_total_mismatch")
        usage_valid = False

    runtime = result.get("runtime_evidence")
    if isinstance(runtime, dict) and (
        "execution_environment" in runtime or "nemoclaw_version" in runtime
    ):
        errors.append("legacy_runtime_fields_present")
    runtime_fields = {
        "completed_at",
        "declared_execution_environment",
        "declared_nemoclaw_version",
        "endpoint_origin",
        "estimated_cost_usd",
        "input_price_usd_per_million",
        "latency_ms",
        "max_completion_tokens",
        "maximum_estimated_cost_usd",
        "model_id",
        "nemoclaw_proof",
        "output_price_usd_per_million",
        "provider",
        "request_sha256",
        "response_sha256",
        "started_at",
        "verbatim_log_sha256",
    }
    if not isinstance(runtime, dict) or set(runtime) != runtime_fields:
        errors.append("runtime_evidence_invalid")
        runtime = {}
    if runtime.get("provider") != result.get("provider"):
        errors.append("runtime_provider_mismatch")
    if runtime.get("model_id") != result.get("model_id"):
        errors.append("runtime_model_mismatch")
    origin = runtime.get("endpoint_origin")
    parsed_origin = urlsplit(origin) if isinstance(origin, str) else None
    if (
        parsed_origin is None
        or parsed_origin.scheme != "https"
        or not parsed_origin.hostname
        or parsed_origin.path not in {"", "/"}
        or parsed_origin.query
        or parsed_origin.fragment
    ):
        errors.append("runtime_endpoint_origin_invalid")
    started = _iso_datetime(runtime.get("started_at"))
    completed = _iso_datetime(runtime.get("completed_at"))
    if started is None or completed is None or completed < started:
        errors.append("runtime_timestamps_invalid")
    latency = runtime.get("latency_ms")
    if isinstance(latency, bool) or not isinstance(latency, int) or latency < 0:
        errors.append("runtime_latency_invalid")
    environment = runtime.get("declared_execution_environment")
    nemoclaw_version = runtime.get("declared_nemoclaw_version")
    if environment not in {"direct", "nemoclaw"}:
        errors.append("declared_runtime_environment_invalid")
    if environment == "nemoclaw" and (
        not isinstance(nemoclaw_version, str) or not nemoclaw_version.strip()
    ):
        errors.append("declared_nemoclaw_version_missing")
    if environment == "direct" and nemoclaw_version is not None:
        errors.append("direct_runtime_has_declared_nemoclaw_version")
    if runtime.get("nemoclaw_proof") is not False:
        errors.append("nemoclaw_proof_unverified")

    numeric_fields = (
        "estimated_cost_usd",
        "input_price_usd_per_million",
        "maximum_estimated_cost_usd",
        "output_price_usd_per_million",
    )
    runtime_costs_valid = not any(
        isinstance(runtime.get(key), bool)
        or not isinstance(runtime.get(key), (int, float))
        or not math.isfinite(runtime[key])
        or runtime[key] < 0
        for key in numeric_fields
    )
    if not runtime_costs_valid:
        errors.append("runtime_cost_fields_invalid")
    max_tokens = runtime.get("max_completion_tokens")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
        errors.append("runtime_max_tokens_invalid")
    if usage_valid and runtime_costs_valid:
        calculated_cost = (
            usage["prompt_tokens"] * runtime["input_price_usd_per_million"]
            + usage["completion_tokens"] * runtime["output_price_usd_per_million"]
        ) / 1_000_000
        if not math.isclose(calculated_cost, runtime["estimated_cost_usd"], abs_tol=1e-9):
            errors.append("runtime_cost_mismatch")
        budget = model.get("max_cost_usd")
        if (
            isinstance(budget, bool)
            or not isinstance(budget, (int, float))
            or not math.isfinite(budget)
            or runtime["maximum_estimated_cost_usd"] > budget
        ):
            errors.append("runtime_budget_exceeded")

    provider_log = result.get("provider_log")
    if not isinstance(provider_log, dict) or set(provider_log) != {"request", "response"}:
        errors.append("provider_log_invalid")
        provider_log = {}
    if _contains_forbidden_secret_key(provider_log):
        errors.append("provider_log_contains_secret_key")
    request_log = provider_log.get("request") if isinstance(provider_log, dict) else None
    response_log = provider_log.get("response") if isinstance(provider_log, dict) else None
    if not isinstance(request_log, dict) or set(request_log) != {
        "body",
        "headers",
        "method",
        "url",
    }:
        errors.append("provider_request_log_invalid")
        request_log = {}
    if not isinstance(response_log, dict) or set(response_log) != {"body", "headers", "status"}:
        errors.append("provider_response_log_invalid")
        response_log = {}
    request_body = request_log.get("body")
    response_body = response_log.get("body")
    if request_log.get("method") != "POST" or not isinstance(request_body, dict):
        errors.append("provider_request_invalid")
    elif request_body.get("model") != result.get("model_id"):
        errors.append("provider_request_model_mismatch")
    request_url = request_log.get("url")
    parsed_request_url = urlsplit(request_url) if isinstance(request_url, str) else None
    request_hostname = parsed_request_url.hostname if parsed_request_url is not None else None
    if (
        parsed_request_url is None
        or parsed_request_url.scheme != "https"
        or parsed_request_url.username is not None
        or parsed_request_url.password is not None
        or parsed_request_url.port not in {None, 443}
        or request_hostname is None
        or not re.fullmatch(
            r"api\.tokenfactory(?:\.[a-z0-9-]+)?\.nebius\.com", request_hostname
        )
        or parsed_request_url.path != "/v1/chat/completions"
        or parsed_request_url.query
        or parsed_request_url.fragment
        or origin != f"https://{request_hostname}"
    ):
        errors.append("provider_request_url_invalid")
    if isinstance(request_body, dict) and isinstance(max_tokens, int) and not isinstance(
        max_tokens, bool
    ):
        try:
            expected_request = expected_token_factory_request(
                job, receipts, max_completion_tokens=max_tokens
            )
        except ValueError:
            errors.append("provider_request_contract_invalid")
        else:
            if request_body != expected_request:
                errors.append("provider_request_package_mismatch")
    if status == "executed" and response_log.get("status") != 200:
        errors.append("executed_provider_status_invalid")
    if runtime:
        if runtime.get("request_sha256") != json_sha256(request_body):
            errors.append("provider_request_hash_mismatch")
        if runtime.get("response_sha256") != json_sha256(response_body):
            errors.append("provider_response_hash_mismatch")
        if runtime.get("verbatim_log_sha256") != json_sha256(provider_log):
            errors.append("provider_log_hash_mismatch")
    attempt_fields = {
        "completed_at",
        "endpoint_origin",
        "http_status",
        "model_id",
        "request_sha256",
        "response_sha256",
        "run_id",
        "schema",
        "started_at",
        "status",
    }
    if set(attempt) != attempt_fields:
        errors.append("transfer_attempt_fields_invalid")
    if attempt.get("schema") != TRANSFER_ATTEMPT_SCHEMA:
        errors.append("transfer_attempt_schema_invalid")
    if attempt.get("status") != "response_received":
        errors.append("transfer_attempt_status_invalid")
    if attempt.get("run_id") != run_id:
        errors.append("transfer_attempt_run_id_mismatch")
    if attempt.get("model_id") != result.get("model_id"):
        errors.append("transfer_attempt_model_mismatch")
    if attempt.get("endpoint_origin") != runtime.get("endpoint_origin"):
        errors.append("transfer_attempt_endpoint_mismatch")
    if attempt.get("started_at") != runtime.get("started_at"):
        errors.append("transfer_attempt_start_mismatch")
    if attempt.get("completed_at") != runtime.get("completed_at"):
        errors.append("transfer_attempt_completion_mismatch")
    if attempt.get("request_sha256") != runtime.get("request_sha256"):
        errors.append("transfer_attempt_request_mismatch")
    if attempt.get("response_sha256") != runtime.get("response_sha256"):
        errors.append("transfer_attempt_response_mismatch")
    if attempt.get("http_status") != response_log.get("status"):
        errors.append("transfer_attempt_status_code_mismatch")
    if status == "executed" and _provider_content(response_body) != result.get("model_output"):
        errors.append("provider_output_mismatch")
    if (
        status == "executed"
        and isinstance(response_body, dict)
        and response_body.get("usage") != usage
    ):
        errors.append("provider_usage_mismatch")
    content_candidates: list[str] = []
    if isinstance(request_body, dict):
        content_candidates.extend(
            item.get("content", "")
            for item in request_body.get("messages", [])
            if isinstance(item, dict)
        )
    if isinstance(response_body, dict):
        choices = response_body.get("choices", [])
        content_candidates.extend(
            item.get("message", {}).get("content", "")
            for item in choices
            if isinstance(item, dict) and isinstance(item.get("message"), dict)
        )
    sensitive = {
        category
        for text in content_candidates
        if isinstance(text, str)
        for category in detect_sensitive_categories(text)
        if category in {"EMAIL", "IBAN", "PATH", "SECRET"}
    }
    errors.extend(f"provider_log_sensitive:{item}" for item in sorted(sensitive))
    return ResultValidation(not errors, run_id, status, _unique(errors))
