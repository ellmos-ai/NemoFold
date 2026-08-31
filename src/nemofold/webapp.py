from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from . import __version__
from .application import ExecutionConfig, preview_job, run_job
from .contracts import RunStatus, to_primitive
from .job_io import ALLOWED_FIELDS, SUPPORTED_WORKFLOWS, JobFileError, parse_job_payload
from .provider_analysis import analyze_with_provider
from .providers import provider_capabilities, provider_config_from_mapping

MAX_REQUEST_BYTES = 512 * 1024
WEB_ROOT = Path(__file__).with_name("web")
CORE_NAMES = (
    "agent_runtime",
    "policy_privacy_gate",
    "run_ledger_recovery",
    "evidence_engine",
    "artifact_export",
    "provider_adapter_core",
    "mcp_surface",
)
PUBLIC_DEMO_INPUT = "demo://synthetic-home"
PUBLIC_DEMO_OUTPUT = "demo://ephemeral"
PUBLIC_DEMO_WORKFLOWS = frozenset(
    {
        "bundle_export",
        "evidence_analyst",
        "folder_digest",
        "platform_proof",
        "version_resolver",
    }
)
PUBLIC_DEMO_PARAMETERS: dict[str, dict[str, object]] = {
    "bundle_export": {
        "bundle_format": "text",
        "bundle_name": "web_bundle",
        "include_manifest": True,
        "order": "display_name",
        "recursive": True,
    },
    "evidence_analyst": {
        "conflict_scan": True,
        "formats": ["md", "txt"],
        "max_chunks": 8,
    },
    "folder_digest": {"digest_depth": "full", "summary_length": 3},
    "platform_proof": {
        "analysis_mode": "local_extractive",
        "evidence_level": "offline",
        "formats": ["md"],
        "max_chunks": 8,
        "network_gate": "closed",
        "runtime": "offline",
    },
    "version_resolver": {"fallback_to_file_time": True},
}
MAX_DEMO_QUESTIONS = 5
MAX_DEMO_QUESTION_CHARS = 500
MAX_DEMO_SOURCE_FILES = 100
MAX_DEMO_SOURCE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class WebAppConfig:
    base_dir: Path
    execution: ExecutionConfig
    exposed_to_network: bool = False
    public_demo: bool = False
    demo_source_root: Path | None = None
    max_parallel_jobs: int = 4

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_dir", Path(self.base_dir).resolve())
        if (
            isinstance(self.max_parallel_jobs, bool)
            or not isinstance(self.max_parallel_jobs, int)
            or not 1 <= self.max_parallel_jobs <= 32
        ):
            raise ValueError("max_parallel_jobs must be between 1 and 32")
        if not self.public_demo:
            if self.demo_source_root is not None:
                raise ValueError("demo_source_root requires public_demo")
            return
        if self.demo_source_root is None:
            raise ValueError("public_demo requires demo_source_root")
        source_root = _validate_public_demo_source(self.demo_source_root)
        if (
            self.execution.external_models_allowed
            or self.execution.apply_actions_allowed
            or self.execution.max_external_cost_usd != 0
        ):
            raise ValueError("public_demo forbids external models, costs, and file actions")
        object.__setattr__(self, "demo_source_root", source_root)


class NemoFoldHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        config: WebAppConfig,
    ) -> None:
        super().__init__(address, NemoFoldRequestHandler)
        self.app_config = config
        self.demo_slots = threading.BoundedSemaphore(config.max_parallel_jobs)


class NemoFoldRequestHandler(BaseHTTPRequestHandler):
    server: NemoFoldHTTPServer
    server_version = "NemoFold/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _headers(self, content_type: str, length: int, status: HTTPStatus) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()

    def _write(self, data: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._headers(content_type, len(data), status)
        self.wfile.write(data)

    def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        self._write(data, "application/json; charset=utf-8", status)

    def _error(self, status: HTTPStatus, code: str, detail: str) -> None:
        self._json({"ok": False, "error": code, "detail": detail}, status)

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc == self.headers.get("Host")

    def _discard_bounded_request_body(self) -> None:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isascii() or not raw_length.isdecimal():
            return
        length = int(raw_length)
        if 0 < length <= MAX_REQUEST_BYTES:
            # Draining an already declared, bounded body prevents Windows from
            # resetting the connection before the 403 response can be read.
            self.rfile.read(length)

    def _read_json(self) -> Any:
        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            raise ValueError("Content-Type must be application/json")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdigit():
            raise ValueError("Content-Length is required")
        length = int(raw_length)
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise ValueError("request body size is invalid")
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path
        static = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
            "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
        }
        if path in static:
            filename, content_type = static[path]
            try:
                data = (WEB_ROOT / filename).read_bytes()
            except OSError:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "asset_missing", filename)
                return
            self._write(data, content_type)
            return
        if path == "/api/status":
            public_demo = self.server.app_config.public_demo
            provider_surface_enabled = not (
                public_demo or self.server.app_config.exposed_to_network
            )
            self._json(
                {
                    "ok": True,
                    "version": __version__,
                    "mode": "public-synthetic-demo" if public_demo else "local-first",
                    "cloud_proof": False,
                    "transfer_performed": False,
                    "live_runtime_ready": False,
                    "provider_surface_enabled": provider_surface_enabled,
                    "provider_runtime_ready": False,
                    "external_models_allowed": (
                        self.server.app_config.execution.external_models_allowed
                        if provider_surface_enabled
                        else False
                    ),
                    "network_exposed": self.server.app_config.exposed_to_network,
                    "public_demo": public_demo,
                    "read_only": public_demo,
                    "synthetic_only": public_demo,
                    "workflows": sorted(
                        PUBLIC_DEMO_WORKFLOWS if public_demo else SUPPORTED_WORKFLOWS
                    ),
                    "cores": list(CORE_NAMES),
                    "providers": provider_capabilities() if provider_surface_enabled else [],
                }
            )
            return
        self._error(HTTPStatus.NOT_FOUND, "not_found", path)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._same_origin():
            self.close_connection = True
            self._discard_bounded_request_body()
            self._error(HTTPStatus.FORBIDDEN, "origin_rejected", "cross-origin request")
            return
        path = urlparse(self.path).path
        if path not in {"/api/preview", "/api/run", "/api/provider-analyze"}:
            self._error(HTTPStatus.NOT_FOUND, "not_found", path)
            return
        if self.server.app_config.public_demo:
            if path == "/api/provider-analyze":
                self._error(HTTPStatus.NOT_FOUND, "not_found", path)
                return
            if not self.server.demo_slots.acquire(blocking=False):
                self._error(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "demo_busy",
                    "all bounded demo slots are in use",
                )
                return
            try:
                self._handle_public_demo(path)
            finally:
                self.server.demo_slots.release()
            return
        if path == "/api/provider-analyze":
            self._handle_provider_analysis()
            return
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            run_id = payload.get("run_id")
            if not isinstance(run_id, str):
                raise ValueError("run_id must be a string")
            job = parse_job_payload(
                payload.get("job"),
                base_dir=self.server.app_config.base_dir,
            )
            result = (
                preview_job(job, self.server.app_config.execution, run_id=run_id)
                if path == "/api/preview"
                else run_job(job, self.server.app_config.execution, run_id=run_id)
            )
        except (JobFileError, json.JSONDecodeError, OSError, RuntimeError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "job_rejected", str(exc))
            return
        report = result.report
        status = (
            HTTPStatus.OK
            if report.status in {RunStatus.PLANNED, RunStatus.EXECUTED}
            else HTTPStatus.CONFLICT
        )
        self._json(
            {
                "ok": status is HTTPStatus.OK,
                "report": to_primitive(report),
                "report_path": str(result.report_path) if result.report_path else None,
            },
            status,
        )

    def _handle_provider_analysis(self) -> None:
        if self.server.app_config.exposed_to_network:
            self._error(
                HTTPStatus.FORBIDDEN,
                "provider_surface_loopback_only",
                "provider analysis is disabled when the HTTP server is network-exposed",
            )
            return
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            unknown = sorted(
                set(payload) - {"run_id", "job", "provider", "approve_external_transfer"}
            )
            if unknown:
                raise ValueError(f"unknown request fields: {', '.join(unknown)}")
            run_id = payload.get("run_id")
            if not isinstance(run_id, str):
                raise ValueError("run_id must be a string")
            provider_value = payload.get("provider")
            if not isinstance(provider_value, dict):
                raise ValueError("provider must be an object")
            approval = payload.get("approve_external_transfer", False)
            if not isinstance(approval, bool):
                raise ValueError("approve_external_transfer must be a boolean")
            job = parse_job_payload(
                payload.get("job"),
                base_dir=self.server.app_config.base_dir,
            )
            result = analyze_with_provider(
                job,
                self.server.app_config.execution,
                provider_config_from_mapping(provider_value),
                run_id=run_id,
                approve_external_transfer=approval,
            )
        except (JobFileError, json.JSONDecodeError, OSError, RuntimeError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "provider_job_rejected", str(exc))
            return
        report = result.report
        status = HTTPStatus.OK if report.status is RunStatus.EXECUTED else HTTPStatus.CONFLICT
        self._json(
            {
                "ok": status is HTTPStatus.OK,
                "report": to_primitive(report),
                "report_path": str(result.report_path) if result.report_path else None,
            },
            status,
        )

    def _handle_public_demo(self, path: str) -> None:
        source_root = self.server.app_config.demo_source_root
        if source_root is None:  # guarded by WebAppConfig; keep request handling fail-closed
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "demo_misconfigured", "source missing")
            return
        replacements = {str(source_root): PUBLIC_DEMO_INPUT}
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            unknown = sorted(set(payload) - {"job"})
            if unknown:
                raise ValueError(f"unknown request fields: {', '.join(unknown)}")
            requested_job = payload.get("job")
            with TemporaryDirectory(prefix="nemofold-public-demo-") as temporary:
                output_root = Path(temporary).resolve()
                replacements[str(output_root)] = PUBLIC_DEMO_OUTPUT
                normalized = _normalize_public_demo_job(
                    requested_job,
                    source_root=source_root,
                    output_root=output_root,
                )
                job = parse_job_payload(normalized, base_dir=source_root.parent)
                execution = ExecutionConfig(
                    allowed_roots=(str(source_root), str(output_root)),
                )
                run_id = f"demo_{uuid4().hex}"
                result = (
                    preview_job(job, execution, run_id=run_id)
                    if path == "/api/preview"
                    else run_job(job, execution, run_id=run_id)
                )
                report = _sanitize_public_demo_value(
                    to_primitive(result.report),
                    replacements=replacements,
                )
        except (JobFileError, json.JSONDecodeError, OSError, RuntimeError, ValueError) as exc:
            detail = _sanitize_public_demo_value(str(exc), replacements=replacements)
            self._error(HTTPStatus.BAD_REQUEST, "job_rejected", detail)
            return
        status = (
            HTTPStatus.OK
            if result.report.status in {RunStatus.PLANNED, RunStatus.EXECUTED}
            else HTTPStatus.CONFLICT
        )
        self._json(
            {
                "ok": status is HTTPStatus.OK,
                "report": report,
                "report_path": None,
                "demo_constraints": {
                    "synthetic_only": True,
                    "ephemeral_output": True,
                    "external_models_allowed": False,
                    "file_actions_allowed": False,
                },
            },
            status,
        )


def _normalize_public_demo_job(
    value: Any,
    *,
    source_root: Path,
    output_root: Path,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise JobFileError("job must be an object")
    unknown = sorted(set(value) - ALLOWED_FIELDS)
    if unknown:
        raise JobFileError(f"unknown fields: {', '.join(unknown)}")
    if value.get("schema") != "nemofold.job.v1":
        raise JobFileError("unsupported job schema")
    workflow = value.get("workflow")
    if workflow not in PUBLIC_DEMO_WORKFLOWS:
        raise JobFileError("workflow is unavailable in the public demo")
    if value.get("input_roots") != [PUBLIC_DEMO_INPUT]:
        raise JobFileError("public demo input_roots are server-controlled")
    if value.get("target_roots", []) != []:
        raise JobFileError("public demo target_roots must be empty")
    if value.get("output_dir") != PUBLIC_DEMO_OUTPUT:
        raise JobFileError("public demo output_dir is server-controlled")
    if value.get("privacy_mode", "local_only") != "local_only":
        raise JobFileError("public demo privacy_mode must be local_only")
    if value.get("action_mode", "dry_run") != "dry_run":
        raise JobFileError("public demo action_mode must be dry_run")
    if value.get("model_id") not in {None, ""}:
        raise JobFileError("public demo does not accept a model_id")
    budget = value.get("model_budget_usd", 0)
    if isinstance(budget, bool) or budget != 0:
        raise JobFileError("public demo model budget must be zero")
    if value.get("resume_run_id") is not None:
        raise JobFileError("public demo does not support resume_run_id")
    if value.get("parameters", {}) != PUBLIC_DEMO_PARAMETERS[workflow]:
        raise JobFileError("public demo parameters are server-controlled")
    questions = value.get("questions", [])
    if not isinstance(questions, list) or any(not isinstance(item, str) for item in questions):
        raise JobFileError("questions must be a list of strings")
    if len(questions) > MAX_DEMO_QUESTIONS or any(
        not item.strip() or len(item) > MAX_DEMO_QUESTION_CHARS for item in questions
    ):
        raise JobFileError("public demo questions exceed the bounded limits")
    if workflow in {"evidence_analyst", "platform_proof"} and not questions:
        raise JobFileError("questions are required for analysis workflows")
    return {
        "schema": "nemofold.job.v1",
        "workflow": workflow,
        "input_roots": [str(source_root)],
        "target_roots": [],
        "output_dir": str(output_root),
        "questions": [item.strip() for item in questions],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "model_budget_usd": 0,
        "parameters": PUBLIC_DEMO_PARAMETERS[workflow],
    }


def _validate_public_demo_source(value: str | Path) -> Path:
    candidate = Path(value)
    if candidate.is_symlink():
        raise ValueError("demo_source_root must not be a symlink")
    source_root = candidate.resolve()
    if not source_root.is_dir():
        raise ValueError("demo_source_root must be an existing directory")
    file_count = 0
    total_bytes = 0
    for item in source_root.rglob("*"):
        if item.is_symlink() or not item.resolve().is_relative_to(source_root):
            raise ValueError("demo_source_root must not contain links outside its boundary")
        if not item.is_file():
            continue
        file_count += 1
        total_bytes += item.stat().st_size
        if file_count > MAX_DEMO_SOURCE_FILES or total_bytes > MAX_DEMO_SOURCE_BYTES:
            raise ValueError("demo_source_root exceeds the bounded corpus limits")
    return source_root


def _sanitize_public_demo_value(value: Any, *, replacements: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_public_demo_value(item, replacements=replacements)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_public_demo_value(item, replacements=replacements) for item in value]
    if isinstance(value, str):
        sanitized = value
        for path, replacement in replacements.items():
            sanitized = sanitized.replace(path, replacement)
            sanitized = sanitized.replace(path.replace("\\", "/"), replacement)
        return sanitized
    return value


def build_server(
    config: WebAppConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> NemoFoldHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    local_hosts = {"127.0.0.1", "::1", "localhost"}
    if host not in local_hosts and not config.exposed_to_network:
        raise PermissionError("non-loopback binding requires explicit network exposure")
    return NemoFoldHTTPServer((host, port), config)


def serve_forever(server: NemoFoldHTTPServer) -> None:
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
