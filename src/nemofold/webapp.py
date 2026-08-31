from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from uuid import uuid4

from . import __version__
from .application import ExecutionConfig, preview_job, run_job
from .contracts import RunStatus, to_primitive
from .drafts import DraftStore
from .job_io import ALLOWED_FIELDS, SUPPORTED_WORKFLOWS, JobFileError, parse_job_payload
from .notebooks import ResearchNotebookStore
from .provider_analysis import analyze_with_provider, preview_provider_context
from .providers import provider_capabilities, provider_config_from_mapping
from .report_verifier import verify_run_report
from .workflow_graphs import workflow_graphs

MAX_REQUEST_BYTES = 512 * 1024
WEB_ROOT = Path(__file__).with_name("web")

# Every static route must resolve inside the package so the console keeps its
# visual identity for any base-dir and for wheel installs; the uncompressed
# theme masters stay in docs/media/designset/sources/. A packaging test walks
# this table and fails when a registered file is missing from the checkout.
STATIC_ROUTES: dict[str, tuple[Path, str]] = {
    "/assets/app.css": (WEB_ROOT / "app.css", "text/css; charset=utf-8"),
    "/assets/app.js": (WEB_ROOT / "app.js", "text/javascript; charset=utf-8"),
    "/assets/theme-document-center.jpg": (
        WEB_ROOT / "assets/theme-document-center.jpg",
        "image/jpeg",
    ),
    "/assets/theme-analysis-lab.jpg": (
        WEB_ROOT / "assets/theme-analysis-lab.jpg",
        "image/jpeg",
    ),
    "/assets/theme-folder-routines.jpg": (
        WEB_ROOT / "assets/theme-folder-routines.jpg",
        "image/jpeg",
    ),
    "/assets/theme-artifact-studio.jpg": (
        WEB_ROOT / "assets/theme-artifact-studio.jpg",
        "image/jpeg",
    ),
    "/assets/theme-connections.jpg": (
        WEB_ROOT / "assets/theme-connections.jpg",
        "image/jpeg",
    ),
}
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
MAX_FOLDER_CHOICES = 500
MAX_GLANCE_FILES = 4000
MAX_GLANCE_NEWEST = 5
MAX_GLANCE_FORMATS = 12
MAX_ARTIFACT_LEDGERS = 200
MAX_LEDGER_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_VIEW_BYTES = 64 * 1024 * 1024


def _api_run_id(value: Any, *, prefix: str = "api") -> str:
    if value is None:
        return f"{prefix}_{uuid4().hex}"
    if not isinstance(value, str):
        raise ValueError("run_id must be a string or null")
    return value


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
    # Bound every socket read/write so a slow client cannot hold a worker
    # thread (and a bounded demo slot) open indefinitely.
    timeout = 30
    server: NemoFoldHTTPServer
    server_version = "NemoFold/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _headers(
        self,
        content_type: str,
        length: int,
        status: HTTPStatus,
        *,
        extra: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
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

    def _reject_before_body_read(self, status: HTTPStatus, code: str, detail: str) -> None:
        # A rejection sent while the declared request body is still unread can
        # reset the connection on Windows before the client reads the response;
        # drain the bounded body first so the error stays readable.
        self._discard_bounded_request_body()
        self._error(status, code, detail)

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
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        page_path = path.rstrip("/") or "/"
        page_routes = {
            "/": "overview",
            "/document-center": "document",
            "/analysis": "analysis",
            "/routines": "routines",
            "/artifacts": "artifacts",
            "/connections": "connections",
        }
        if page_path in page_routes:
            try:
                page = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
            except OSError:
                self._error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "asset_missing",
                    str(WEB_ROOT / "index.html"),
                )
                return
            page = page.replace(
                'data-page="overview"',
                f'data-page="{page_routes[page_path]}"',
                1,
            )
            self._write(page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path in STATIC_ROUTES:
            filename, content_type = STATIC_ROUTES[path]
            try:
                data = filename.read_bytes()
            except OSError:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "asset_missing", filename.name)
                return
            self._write(data, content_type)
            return
        if path == "/api/status":
            public_demo = self.server.app_config.public_demo
            provider_surface_enabled = not (
                public_demo or self.server.app_config.exposed_to_network
            )
            available_workflows = (
                PUBLIC_DEMO_WORKFLOWS if public_demo else SUPPORTED_WORKFLOWS
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
                    "folder_picker_enabled": provider_surface_enabled,
                    "artifact_surface_enabled": provider_surface_enabled,
                    "draft_surface_enabled": provider_surface_enabled,
                    "notebook_surface_enabled": provider_surface_enabled,
                    "external_models_allowed": (
                        self.server.app_config.execution.external_models_allowed
                        if provider_surface_enabled
                        else False
                    ),
                    "network_exposed": self.server.app_config.exposed_to_network,
                    "public_demo": public_demo,
                    "read_only": public_demo,
                    "synthetic_only": public_demo,
                    "workflows": sorted(available_workflows),
                    "workflow_graphs": workflow_graphs(available_workflows),
                    "cores": list(CORE_NAMES),
                    "providers": provider_capabilities() if provider_surface_enabled else [],
                }
            )
            return
        if path == "/api/drafts":
            self._handle_draft_list()
            return
        if path == "/api/draft":
            self._handle_draft_load(parse_qs(parsed_path.query, keep_blank_values=True))
            return
        if path == "/api/notebooks":
            self._handle_notebook_list()
            return
        if path == "/api/notebook":
            self._handle_notebook_load(parse_qs(parsed_path.query, keep_blank_values=True))
            return
        if path == "/api/artifact":
            self._handle_artifact_file(parse_qs(parsed_path.query, keep_blank_values=True))
            return
        self._error(HTTPStatus.NOT_FOUND, "not_found", path)

    def _host_is_trusted(self) -> bool:
        # The Origin/Host comparison alone is spoofable through DNS rebinding:
        # a hostile domain resolving to 127.0.0.1 presents matching headers.
        # On a loopback-only server the Host authority must itself be local.
        if self.server.app_config.exposed_to_network:
            return True
        host = self.headers.get("Host", "")
        hostname = urlparse(f"//{host}").hostname or ""
        return hostname in {"127.0.0.1", "localhost", "::1"}

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._host_is_trusted():
            self.close_connection = True
            self._discard_bounded_request_body()
            self._error(HTTPStatus.FORBIDDEN, "host_rejected", "non-local Host header")
            return
        if not self._same_origin():
            self.close_connection = True
            self._discard_bounded_request_body()
            self._error(HTTPStatus.FORBIDDEN, "origin_rejected", "cross-origin request")
            return
        path = urlparse(self.path).path
        if path not in {
            "/api/preview",
            "/api/run",
            "/api/provider-analyze",
            "/api/provider-preview",
            "/api/folders",
            "/api/corpus-glance",
            "/api/artifacts",
            "/api/drafts",
            "/api/notebooks",
            "/api/notebook-run",
        }:
            self._discard_bounded_request_body()
            self._error(HTTPStatus.NOT_FOUND, "not_found", path)
            return
        if self.server.app_config.public_demo:
            if path in {
                "/api/provider-analyze",
                "/api/provider-preview",
                "/api/folders",
                "/api/corpus-glance",
                "/api/artifacts",
                "/api/drafts",
                "/api/notebooks",
                "/api/notebook-run",
            }:
                self._discard_bounded_request_body()
                self._error(HTTPStatus.NOT_FOUND, "not_found", path)
                return
            if not self.server.demo_slots.acquire(blocking=False):
                # Same Windows reset race as the cross-origin 403: reject with
                # the declared bounded body drained so the client can read 429.
                self._discard_bounded_request_body()
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
        if self.server.app_config.exposed_to_network and path in {"/api/preview", "/api/run"}:
            # Every other authority-bearing surface disables itself when the
            # server is network-exposed; job preview/execution must not be the
            # one unauthenticated exception. Hosting goes through serve-demo.
            self._discard_bounded_request_body()
            self._error(
                HTTPStatus.FORBIDDEN,
                "job_surface_loopback_only",
                "job preview and execution are disabled when the HTTP server is network-exposed",
            )
            return
        if path == "/api/provider-analyze":
            self._handle_provider_analysis()
            return
        if path == "/api/provider-preview":
            self._handle_provider_preview()
            return
        if path == "/api/folders":
            self._handle_folder_browser()
            return
        if path == "/api/corpus-glance":
            self._handle_corpus_glance()
            return
        if path == "/api/artifacts":
            self._handle_artifact_catalog()
            return
        if path == "/api/drafts":
            self._handle_draft_save()
            return
        if path == "/api/notebooks":
            self._handle_notebook_save()
            return
        if path == "/api/notebook-run":
            self._handle_notebook_run_link()
            return
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            run_id = _api_run_id(payload.get("run_id"))
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
            self._reject_before_body_read(
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
            run_id = _api_run_id(payload.get("run_id"), prefix="api_provider")
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

    def _handle_provider_preview(self) -> None:
        if self.server.app_config.exposed_to_network:
            self._reject_before_body_read(
                HTTPStatus.FORBIDDEN,
                "provider_surface_loopback_only",
                "provider preview is disabled when the HTTP server is network-exposed",
            )
            return
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            unknown = sorted(set(payload) - {"run_id", "job", "provider"})
            if unknown:
                raise ValueError(f"unknown request fields: {', '.join(unknown)}")
            run_id = _api_run_id(payload.get("run_id"), prefix="api_preview")
            provider_value = payload.get("provider")
            if not isinstance(provider_value, dict):
                raise ValueError("provider must be an object")
            job = parse_job_payload(
                payload.get("job"),
                base_dir=self.server.app_config.base_dir,
            )
            result = preview_provider_context(
                job,
                self.server.app_config.execution,
                provider_config_from_mapping(provider_value),
                run_id=run_id,
            )
        except (JobFileError, json.JSONDecodeError, OSError, RuntimeError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "provider_preview_rejected", str(exc))
            return
        self._json({"ok": True, "preview": result})

    def _handle_folder_browser(self) -> None:
        if self.server.app_config.exposed_to_network:
            self._reject_before_body_read(
                HTTPStatus.FORBIDDEN,
                "folder_picker_loopback_only",
                "folder browsing is disabled when the HTTP server is network-exposed",
            )
            return
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            unknown = sorted(set(payload) - {"path"})
            if unknown:
                raise ValueError(f"unknown request fields: {', '.join(unknown)}")
            path = payload.get("path")
            if path is not None and not isinstance(path, str):
                raise ValueError("path must be a string or null")
            result = _folder_listing(
                self.server.app_config,
                requested_path=path,
            )
        except (OSError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "folder_rejected", str(exc))
            return
        self._json({"ok": True, **result})

    def _handle_corpus_glance(self) -> None:
        if self.server.app_config.exposed_to_network:
            self._reject_before_body_read(
                HTTPStatus.FORBIDDEN,
                "corpus_glance_loopback_only",
                "corpus overview is disabled when the HTTP server is network-exposed",
            )
            return
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            unknown = sorted(set(payload) - {"path"})
            if unknown:
                raise ValueError(f"unknown request fields: {', '.join(unknown)}")
            path = payload.get("path")
            if path is not None and not isinstance(path, str):
                raise ValueError("path must be a string or null")
            result = _corpus_glance(self.server.app_config, requested_path=path)
        except (OSError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "corpus_glance_rejected", str(exc))
            return
        self._json({"ok": True, **result})

    def _handle_artifact_catalog(self) -> None:
        if self.server.app_config.exposed_to_network:
            self._reject_before_body_read(
                HTTPStatus.FORBIDDEN,
                "artifact_surface_loopback_only",
                "artifact browsing is disabled when the HTTP server is network-exposed",
            )
            return
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            unknown = sorted(set(payload) - {"output_dir"})
            if unknown:
                raise ValueError(f"unknown request fields: {', '.join(unknown)}")
            output_dir = payload.get("output_dir")
            if not isinstance(output_dir, str) or not output_dir.strip():
                raise ValueError("output_dir must be a non-empty string")
            result = _artifact_catalog(self.server.app_config, output_dir)
        except (OSError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "artifact_catalog_rejected", str(exc))
            return
        self._json({"ok": True, **result})

    def _draft_store(self) -> DraftStore:
        return DraftStore(
            self.server.app_config.base_dir,
            self.server.app_config.execution.allowed_roots,
        )

    def _draft_surface_available(self) -> bool:
        return not (
            self.server.app_config.public_demo or self.server.app_config.exposed_to_network
        )

    def _notebook_store(self) -> ResearchNotebookStore:
        return ResearchNotebookStore(
            self.server.app_config.base_dir,
            self.server.app_config.execution.allowed_roots,
        )

    def _handle_draft_list(self) -> None:
        if not self._draft_surface_available():
            self._error(HTTPStatus.NOT_FOUND, "not_found", "/api/drafts")
            return
        try:
            drafts = self._draft_store().list()
        except (OSError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "draft_inbox_unavailable", str(exc))
            return
        self._json({"ok": True, "drafts": drafts})

    def _handle_draft_load(self, query: dict[str, list[str]]) -> None:
        if not self._draft_surface_available():
            self._error(HTTPStatus.NOT_FOUND, "not_found", "/api/draft")
            return
        try:
            if set(query) != {"id"} or len(query["id"]) != 1:
                raise ValueError("one draft id is required")
            draft = self._draft_store().load(query["id"][0])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "draft_load_rejected", str(exc))
            return
        self._json({"ok": True, "draft": draft})

    def _handle_draft_save(self) -> None:
        if not self._draft_surface_available():
            self._reject_before_body_read(HTTPStatus.NOT_FOUND, "not_found", "/api/drafts")
            return
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            unknown = sorted(set(payload) - {"job", "provider", "name"})
            if unknown:
                raise ValueError(f"unknown request fields: {', '.join(unknown)}")
            provider = payload.get("provider")
            if provider is not None and not isinstance(provider, dict):
                raise ValueError("provider must be an object or null")
            name = payload.get("name")
            if name is not None and not isinstance(name, str):
                raise ValueError("name must be a string or null")
            job = payload.get("job")
            if not isinstance(job, dict):
                raise ValueError("job must be an object")
            draft = self._draft_store().save(
                job,
                provider=provider,
                name=name,
                source="api",
            )
        except (JobFileError, OSError, PermissionError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "draft_save_rejected", str(exc))
            return
        self._json({"ok": True, "draft": draft}, HTTPStatus.CREATED)

    def _handle_notebook_list(self) -> None:
        if not self._draft_surface_available():
            self._error(HTTPStatus.NOT_FOUND, "not_found", "/api/notebooks")
            return
        try:
            notebooks = self._notebook_store().list()
        except (OSError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "notebook_store_unavailable", str(exc))
            return
        self._json({"ok": True, "notebooks": notebooks})

    def _handle_notebook_load(self, query: dict[str, list[str]]) -> None:
        if not self._draft_surface_available():
            self._error(HTTPStatus.NOT_FOUND, "not_found", "/api/notebook")
            return
        try:
            if set(query) != {"id"} or len(query["id"]) != 1:
                raise ValueError("one research notebook id is required")
            notebook = self._notebook_store().load(query["id"][0])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "notebook_load_rejected", str(exc))
            return
        self._json({"ok": True, "notebook": notebook})

    def _handle_notebook_save(self) -> None:
        if not self._draft_surface_available():
            self._reject_before_body_read(HTTPStatus.NOT_FOUND, "not_found", "/api/notebooks")
            return
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            notebook = self._notebook_store().save(payload)
        except (OSError, PermissionError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "notebook_save_rejected", str(exc))
            return
        self._json({"ok": True, "notebook": notebook}, HTTPStatus.CREATED)

    def _handle_notebook_run_link(self) -> None:
        if not self._draft_surface_available():
            self._reject_before_body_read(HTTPStatus.NOT_FOUND, "not_found", "/api/notebook-run")
            return
        try:
            payload = self._read_json()
            if not isinstance(payload, dict) or set(payload) != {"notebook_id", "run_id"}:
                raise ValueError("notebook_id and run_id are required")
            notebook_id = payload.get("notebook_id")
            run_id = payload.get("run_id")
            if not isinstance(notebook_id, str) or not isinstance(run_id, str):
                raise ValueError("notebook_id and run_id must be strings")
            notebook = self._notebook_store().link_run(notebook_id, run_id)
        except (OSError, PermissionError, ValueError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "notebook_run_rejected", str(exc))
            return
        self._json({"ok": True, "notebook": notebook})

    def _handle_artifact_file(self, query: dict[str, list[str]]) -> None:
        if self.server.app_config.public_demo:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "/api/artifact")
            return
        if self.server.app_config.exposed_to_network:
            self._error(
                HTTPStatus.FORBIDDEN,
                "artifact_surface_loopback_only",
                "artifact viewing is disabled when the HTTP server is network-exposed",
            )
            return
        try:
            if set(query) != {"output_dir", "path"}:
                raise ValueError("output_dir and path are required")
            output_values = query["output_dir"]
            path_values = query["path"]
            if len(output_values) != 1 or len(path_values) != 1:
                raise ValueError("output_dir and path must be singular")
            artifact = _registered_artifact_path(
                self.server.app_config,
                output_values[0],
                path_values[0],
            )
            size = artifact.stat().st_size
            if size > MAX_ARTIFACT_VIEW_BYTES:
                raise ValueError("artifact exceeds the browser-view size limit")
            data = artifact.read_bytes()
        except (OSError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "artifact_view_rejected", str(exc))
            return
        suffix = artifact.suffix.casefold()
        content_type = "application/pdf" if suffix == ".pdf" else "text/plain; charset=utf-8"
        disposition = "inline" if suffix in {".json", ".md", ".pdf", ".txt"} else "attachment"
        filename = quote(artifact.name, safe="")
        self._headers(
            content_type,
            len(data),
            HTTPStatus.OK,
            extra={"Content-Disposition": f"{disposition}; filename*=UTF-8''{filename}"},
        )
        self.wfile.write(data)

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


def _corpus_glance(
    config: WebAppConfig,
    *,
    requested_path: str | None,
) -> dict[str, object]:
    """Bounded, read-only look at what lives inside one approved root.

    Powers the per-area "home" modules of the console: counts and recency
    only, never file contents; capped so a huge corpus cannot stall the
    request thread.
    """
    roots = _allowed_folder_roots(config)
    if requested_path is None:
        if not roots:
            raise ValueError("no approved corpus root is available")
        candidate = roots[0]
    else:
        raw_candidate = Path(requested_path)
        candidate = (
            raw_candidate if raw_candidate.is_absolute() else config.base_dir / raw_candidate
        ).resolve()
    root = _matching_folder_root(candidate, roots)
    if root is None:
        raise PermissionError("folder is outside the server-approved roots")
    if not candidate.is_dir():
        raise ValueError("folder must be an existing directory")
    total_files = 0
    total_bytes = 0
    by_format: dict[str, int] = {}
    newest: list[tuple[float, dict[str, object]]] = []
    truncated = False
    pending: list[Path] = [candidate]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            continue
        for item in entries:
            if item.is_symlink():
                continue
            if item.is_dir():
                pending.append(item)
                continue
            if not item.is_file():
                continue
            if total_files >= MAX_GLANCE_FILES:
                truncated = True
                pending.clear()
                break
            try:
                stat = item.stat()
            except OSError:
                continue
            total_files += 1
            total_bytes += stat.st_size
            suffix = item.suffix.lower().lstrip(".") or "none"
            by_format[suffix] = by_format.get(suffix, 0) + 1
            record = {
                "name": item.name,
                "relative_path": str(item.relative_to(candidate)),
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(
                    timespec="seconds"
                ),
                "bytes": stat.st_size,
            }
            newest.append((stat.st_mtime, record))
            newest.sort(key=lambda pair: pair[0], reverse=True)
            del newest[MAX_GLANCE_NEWEST:]
    formats = dict(
        sorted(by_format.items(), key=lambda pair: (-pair[1], pair[0]))[:MAX_GLANCE_FORMATS]
    )
    return {
        "root": str(candidate),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "by_format": formats,
        "newest": [record for _, record in newest],
        "truncated": truncated,
    }


def _allowed_folder_roots(config: WebAppConfig) -> tuple[Path, ...]:
    roots: list[Path] = []
    for value in config.execution.allowed_roots:
        candidate = Path(value).resolve()
        if candidate.is_dir() and candidate not in roots:
            roots.append(candidate)
    return tuple(roots)


def _matching_folder_root(candidate: Path, roots: tuple[Path, ...]) -> Path | None:
    return next(
        (
            root
            for root in roots
            if candidate == root or candidate.is_relative_to(root)
        ),
        None,
    )


def _folder_listing(
    config: WebAppConfig,
    *,
    requested_path: str | None,
) -> dict[str, object]:
    roots = _allowed_folder_roots(config)
    root_values = [
        {"name": root.name or str(root), "path": str(root)}
        for root in roots
    ]
    if requested_path is None:
        return {
            "roots": root_values,
            "current": None,
            "parent": None,
            "directories": [],
            "truncated": False,
        }
    raw_candidate = Path(requested_path)
    candidate = (
        raw_candidate if raw_candidate.is_absolute() else config.base_dir / raw_candidate
    ).resolve()
    root = _matching_folder_root(candidate, roots)
    if root is None:
        raise PermissionError("folder is outside the server-approved roots")
    if not candidate.is_dir():
        raise ValueError("folder must be an existing directory")
    directories: list[dict[str, str]] = []
    skipped = 0
    for item in sorted(candidate.iterdir(), key=lambda path: path.name.casefold()):
        if item.is_symlink():
            skipped += 1
            continue
        try:
            resolved = item.resolve()
            if not resolved.is_dir() or _matching_folder_root(resolved, (root,)) is None:
                continue
        except OSError:
            skipped += 1
            continue
        if len(directories) == MAX_FOLDER_CHOICES:
            skipped += 1
            continue
        directories.append({"name": item.name, "path": str(resolved)})
    parent = None
    if candidate != root:
        parent_candidate = candidate.parent.resolve()
        if _matching_folder_root(parent_candidate, (root,)) is not None:
            parent = str(parent_candidate)
    return {
        "roots": root_values,
        "current": {"name": candidate.name or str(candidate), "path": str(candidate)},
        "parent": parent,
        "directories": directories,
        "skipped_count": skipped,
        "truncated": len(directories) == MAX_FOLDER_CHOICES and skipped > 0,
    }


def _allowed_output_root(config: WebAppConfig, value: str) -> Path:
    raw = Path(value)
    output = (raw if raw.is_absolute() else config.base_dir / raw).resolve()
    if _matching_folder_root(output, _allowed_folder_roots(config)) is None:
        raise PermissionError("output directory is outside the server-approved roots")
    if output.exists() and (not output.is_dir() or output.is_symlink()):
        raise ValueError("output directory must be a real directory")
    return output


def _ledger_paths(output: Path) -> tuple[Path, ...]:
    ledger_root = output / "ledger"
    if not ledger_root.is_dir() or ledger_root.is_symlink():
        return ()
    candidates: list[tuple[int, Path]] = []
    for path in ledger_root.glob("*.json"):
        try:
            if path.is_file() and not path.is_symlink():
                candidates.append((path.stat().st_mtime_ns, path.resolve()))
        except OSError:
            continue
    candidates.sort(key=lambda item: (item[0], item[1].name.casefold()), reverse=True)
    return tuple(path for _, path in candidates[:MAX_ARTIFACT_LEDGERS])


def _load_ledger(path: Path) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > MAX_LEDGER_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _artifact_record_path(output: Path, value: str) -> Path:
    raw = Path(value)
    return (raw if raw.is_absolute() else output / raw).resolve()


def _artifact_catalog(config: WebAppConfig, output_dir: str) -> dict[str, object]:
    output = _allowed_output_root(config, output_dir)
    runs: list[dict[str, object]] = []
    for ledger in _ledger_paths(output):
        payload = _load_ledger(ledger)
        if payload is None:
            continue
        verification = verify_run_report(ledger, allowed_roots=(output,))
        artifacts: list[dict[str, object]] = []
        records = payload.get("artifacts")
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                continue
            path = _artifact_record_path(output, record["path"])
            within_output = path == output or path.is_relative_to(output)
            available = (
                verification.valid
                and within_output
                and path.is_file()
                and not path.is_symlink()
            )
            artifacts.append(
                {
                    "format": str(record.get("format") or path.suffix.lstrip(".") or "file"),
                    "name": path.name,
                    "path": str(path),
                    "sha256": record.get("sha256"),
                    "status": record.get("status", "unknown"),
                    "available": available,
                }
            )
        errors = payload.get("errors")
        runs.append(
            {
                "run_id": payload.get("run_id", ledger.stem),
                "workflow": payload.get("workflow", "unknown"),
                "status": payload.get("status", "unknown"),
                "errors": errors if isinstance(errors, list) else [],
                "ledger_path": str(ledger),
                "verification": {
                    "valid": verification.valid,
                    "checked_artifacts": verification.checked_artifacts,
                    "errors": list(verification.errors),
                },
                "artifacts": artifacts,
            }
        )
    return {
        "output_dir": str(output),
        "runs": runs,
        "truncated": len(_ledger_paths(output)) == MAX_ARTIFACT_LEDGERS,
        "verification_note": (
            "green means the ledger contract and every recorded artifact hash passed"
        ),
    }


def _registered_artifact_path(config: WebAppConfig, output_dir: str, value: str) -> Path:
    output = _allowed_output_root(config, output_dir)
    candidate = _artifact_record_path(output, value)
    if not candidate.is_relative_to(output) or not candidate.is_file() or candidate.is_symlink():
        raise PermissionError("artifact is unavailable or outside the selected output directory")
    for ledger in _ledger_paths(output):
        if candidate == ledger:
            return candidate
        if not verify_run_report(ledger, allowed_roots=(output,)).valid:
            continue
        payload = _load_ledger(ledger)
        records = payload.get("artifacts") if payload is not None else None
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                continue
            if _artifact_record_path(output, record["path"]) == candidate:
                return candidate
    raise PermissionError("file is not registered by a NemoFold run ledger")


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
