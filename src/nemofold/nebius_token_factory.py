from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .anonymizer import pseudonymize_text
from .artifacts import write_text_artifact
from .live_result import (
    RESULT_SCHEMA,
    TRANSFER_ATTEMPT_SCHEMA,
    expected_token_factory_request,
    json_sha256,
    validate_model_output,
    validate_result_package,
)
from .nemoclaw_package import TRANSFER_ATTEMPT_FILENAME, validate_job_package

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class TokenFactoryConfig:
    api_key: str
    input_price_usd_per_million: float
    output_price_usd_per_million: float
    max_completion_tokens: int = 1200
    timeout_seconds: float = 60.0
    base_url: str = DEFAULT_BASE_URL
    nemoclaw_version: str | None = None

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("Nebius API key is missing")
        for name, value in (
            ("input price", self.input_price_usd_per_million),
            ("output price", self.output_price_usd_per_million),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if (
            isinstance(self.max_completion_tokens, bool)
            or not isinstance(self.max_completion_tokens, int)
            or not 1 <= self.max_completion_tokens <= 65_536
        ):
            raise ValueError("max completion tokens must be between 1 and 65536")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 1 <= self.timeout_seconds <= 300
        ):
            raise ValueError("timeout must be between 1 and 300 seconds")
        if self.nemoclaw_version is not None and not self.nemoclaw_version.strip():
            raise ValueError("NemoClaw version must not be blank")


@dataclass(frozen=True, slots=True)
class HTTPExchange:
    status: int
    headers: dict[str, str]
    body: bytes


class TokenFactoryTransport(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> HTTPExchange: ...


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        return None


class UrllibTokenFactoryTransport:
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> HTTPExchange:
        request = Request(url, data=body, headers=headers, method="POST")
        opener = build_opener(_RejectRedirects())
        try:
            response = opener.open(request, timeout=timeout_seconds)  # noqa: S310
        except HTTPError as exc:
            response = exc
        with response:
            content = response.read(MAX_RESPONSE_BYTES + 1)
            if len(content) > MAX_RESPONSE_BYTES:
                raise ValueError("Token Factory response exceeded the size limit")
            return HTTPExchange(
                status=int(response.status),
                headers={
                    str(key).casefold(): str(value)
                    for key, value in response.headers.items()
                },
                body=content,
            )


def token_factory_endpoint(base_url: str) -> tuple[str, str]:
    parsed = urlsplit(base_url)
    hostname = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or not re.fullmatch(r"api\.tokenfactory(?:\.[a-z0-9-]+)?\.nebius\.com", hostname)
        or parsed.path.rstrip("/") != "/v1"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Token Factory base URL is outside the approved Nebius endpoint scope")
    origin = f"https://{hostname}"
    return f"{origin}/v1/chat/completions", origin


def _load_package(path: Path) -> tuple[dict[str, Any], list[Any]]:
    job = json.loads((path / "job.json").read_text(encoding="utf-8"))
    receipts = json.loads((path / "context-receipts.json").read_text(encoding="utf-8"))
    if not isinstance(job, dict) or not isinstance(receipts, list):
        raise ValueError("NemoClaw package payload is invalid")
    return job, receipts


def build_token_factory_request(
    job: dict[str, Any],
    receipts: list[Any],
    *,
    max_completion_tokens: int,
) -> dict[str, Any]:
    return expected_token_factory_request(
        job, receipts, max_completion_tokens=max_completion_tokens
    )


def maximum_estimated_cost_usd(
    request_body: dict[str, Any], config: TokenFactoryConfig
) -> float:
    conservative_input_token_bound = len(
        json.dumps(request_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return (
        (conservative_input_token_bound + 1) * config.input_price_usd_per_million
        + config.max_completion_tokens * config.output_price_usd_per_million
    ) / 1_000_000


def _create_transfer_attempt(path: Path, attempt: dict[str, Any]) -> None:
    data = (json.dumps(attempt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        handle = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise FileExistsError(
            "result or transfer attempt already exists; refusing a duplicate paid request"
        ) from exc
    with os.fdopen(handle, "wb") as attempt_file:
        attempt_file.write(data)
        attempt_file.flush()
        os.fsync(attempt_file.fileno())


def _parse_response_body(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        decoded = raw.decode("utf-8", errors="replace")
        cleaned = pseudonymize_text(decoded[:32_768]).text
        return {"raw_text": cleaned, "raw_sha256": hashlib.sha256(raw).hexdigest()}
    return value if isinstance(value, dict) else {"unexpected_json": value}


def _usage(response_body: dict[str, Any]) -> tuple[dict[str, int], list[str]]:
    value = response_body.get("usage")
    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    if (
        not isinstance(value, dict)
        or any(
            isinstance(value.get(field), bool)
            or not isinstance(value.get(field), int)
            or value[field] < 0
            for field in fields
        )
        or value["total_tokens"] != value["prompt_tokens"] + value["completion_tokens"]
    ):
        return {field: 0 for field in fields}, ["provider_usage_invalid"]
    return {field: value[field] for field in fields}, []


def _model_output(response_body: dict[str, Any]) -> tuple[Any, list[str]]:
    try:
        choice = response_body["choices"][0]
        content = choice["message"]["content"]
        finish_reason = choice["finish_reason"]
    except (IndexError, KeyError, TypeError):
        return None, ["provider_completion_contract_invalid"]
    errors: list[str] = []
    if finish_reason != "stop":
        errors.append(f"provider_finish_reason:{finish_reason}")
    if not isinstance(content, str):
        return None, errors + ["provider_content_invalid"]
    try:
        return json.loads(content), errors
    except json.JSONDecodeError:
        return None, errors + ["provider_content_not_json"]


def run_token_factory_package(
    path: str | Path,
    config: TokenFactoryConfig,
    *,
    approve_live_transfer: bool,
    transport: TokenFactoryTransport | None = None,
) -> Path:
    package_path = Path(path)
    if not approve_live_transfer:
        raise PermissionError("live Token Factory transfer requires explicit approval")
    validation = validate_job_package(package_path)
    if not validation.valid:
        raise ValueError(f"NemoClaw package is invalid: {', '.join(validation.errors)}")
    result_path = package_path / "result.json"
    attempt_path = package_path / TRANSFER_ATTEMPT_FILENAME
    if result_path.exists() or attempt_path.exists():
        raise FileExistsError(
            "result or transfer attempt already exists; refusing a duplicate paid request"
        )
    job, receipts = _load_package(package_path)
    request_body = build_token_factory_request(
        job,
        receipts,
        max_completion_tokens=config.max_completion_tokens,
    )
    maximum_cost = maximum_estimated_cost_usd(request_body, config)
    model_value = job.get("model")
    model: dict[str, Any] = model_value if isinstance(model_value, dict) else {}
    model_id = model.get("id")
    if not isinstance(model_id, str) or not model_id.startswith("nvidia/nemotron-"):
        raise PermissionError(
            "competition live adapter requires an explicit NVIDIA Nemotron model ID"
        )
    budget = model.get("max_cost_usd") if isinstance(model, dict) else None
    if (
        isinstance(budget, bool)
        or not isinstance(budget, (int, float))
        or not math.isfinite(budget)
        or maximum_cost > budget
    ):
        raise PermissionError("conservative Token Factory cost bound exceeds the job budget")
    endpoint, origin = token_factory_endpoint(config.base_url)
    request_bytes = (
        json.dumps(request_body, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    started = datetime.now(UTC)
    attempt = {
        "schema": TRANSFER_ATTEMPT_SCHEMA,
        "run_id": job.get("run_id"),
        "status": "request_ready",
        "model_id": model_id,
        "endpoint_origin": origin,
        "started_at": started.isoformat(),
        "completed_at": None,
        "request_sha256": json_sha256(request_body),
        "response_sha256": None,
        "http_status": None,
    }
    _create_transfer_attempt(attempt_path, attempt)
    monotonic_start = time.monotonic()
    exchange = (transport or UrllibTokenFactoryTransport()).post(
        endpoint,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "NemoFold/0.1",
        },
        body=request_bytes,
        timeout_seconds=config.timeout_seconds,
    )
    latency_ms = max(0, round((time.monotonic() - monotonic_start) * 1000))
    completed = datetime.now(UTC)
    response_body = _parse_response_body(exchange.body)
    attempt.update(
        {
            "status": "response_received",
            "completed_at": completed.isoformat(),
            "response_sha256": json_sha256(response_body),
            "http_status": exchange.status,
        }
    )
    write_text_artifact(
        attempt_path,
        json.dumps(attempt, indent=2, sort_keys=True) + "\n",
        "transfer-attempt",
    )
    usage, errors = _usage(response_body)
    output, output_errors = _model_output(response_body)
    errors.extend(output_errors)
    if exchange.status != 200:
        errors.append(f"provider_http_status:{exchange.status}")
    if output is not None:
        errors.extend(validate_model_output(job, receipts, output))
    estimated_cost = (
        usage["prompt_tokens"] * config.input_price_usd_per_million
        + usage["completion_tokens"] * config.output_price_usd_per_million
    ) / 1_000_000
    if estimated_cost > budget:
        errors.append("actual_token_cost_exceeds_job_budget")
    safe_response_headers = {
        key: value
        for key, value in exchange.headers.items()
        if key.casefold() in {"content-type", "date", "x-request-id"}
    }
    provider_log = {
        "request": {
            "method": "POST",
            "url": endpoint,
            "headers": {
                "accept": "application/json",
                "content-type": "application/json",
                "user-agent": "NemoFold/0.1",
            },
            "body": request_body,
        },
        "response": {
            "status": exchange.status,
            "headers": safe_response_headers,
            "body": response_body,
        },
    }
    status = "failed" if errors else "executed"
    runtime_evidence = {
        "provider": "nebius-token-factory",
        "endpoint_origin": origin,
        "model_id": model_id,
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "latency_ms": latency_ms,
        "request_sha256": json_sha256(request_body),
        "response_sha256": json_sha256(response_body),
        "verbatim_log_sha256": json_sha256(provider_log),
        "input_price_usd_per_million": config.input_price_usd_per_million,
        "output_price_usd_per_million": config.output_price_usd_per_million,
        "estimated_cost_usd": estimated_cost,
        "maximum_estimated_cost_usd": maximum_cost,
        "max_completion_tokens": config.max_completion_tokens,
        "execution_environment": "nemoclaw" if config.nemoclaw_version else "direct",
        "nemoclaw_version": config.nemoclaw_version,
    }
    result = {
        "schema": RESULT_SCHEMA,
        "run_id": job.get("run_id"),
        "status": status,
        "errors": list(dict.fromkeys(errors)),
        "response_schema": job.get("response_schema"),
        "provider": "nebius-token-factory",
        "model_id": model_id,
        "transfer_performed": True,
        "cloud_proof": status == "executed",
        "model_output": output,
        "usage": usage,
        "runtime_evidence": runtime_evidence,
        "provider_log": provider_log,
    }
    write_text_artifact(
        result_path,
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        "live-result",
    )
    result_validation = validate_result_package(package_path)
    if not result_validation.valid:
        raise RuntimeError(
            f"created live result is invalid: {', '.join(result_validation.errors)}"
        )
    return result_path
