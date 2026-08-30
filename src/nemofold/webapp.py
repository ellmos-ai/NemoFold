from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import __version__
from .application import ExecutionConfig, preview_job, run_job
from .contracts import RunStatus, to_primitive
from .job_io import SUPPORTED_WORKFLOWS, JobFileError, parse_job_payload

MAX_REQUEST_BYTES = 512 * 1024
WEB_ROOT = Path(__file__).with_name("web")
CORE_NAMES = (
    "agent_runtime",
    "policy_privacy_gate",
    "run_ledger_recovery",
    "evidence_engine",
    "artifact_export",
)


@dataclass(frozen=True, slots=True)
class WebAppConfig:
    base_dir: Path
    execution: ExecutionConfig
    exposed_to_network: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_dir", Path(self.base_dir).resolve())


class NemoFoldHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        config: WebAppConfig,
    ) -> None:
        super().__init__(address, NemoFoldRequestHandler)
        self.app_config = config


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
            self._json(
                {
                    "ok": True,
                    "version": __version__,
                    "mode": "local-first",
                    "cloud_proof": False,
                    "transfer_performed": False,
                    "live_runtime_ready": False,
                    "network_exposed": self.server.app_config.exposed_to_network,
                    "workflows": sorted(SUPPORTED_WORKFLOWS),
                    "cores": list(CORE_NAMES),
                }
            )
            return
        self._error(HTTPStatus.NOT_FOUND, "not_found", path)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._same_origin():
            self._error(HTTPStatus.FORBIDDEN, "origin_rejected", "cross-origin request")
            return
        path = urlparse(self.path).path
        if path not in {"/api/preview", "/api/run"}:
            self._error(HTTPStatus.NOT_FOUND, "not_found", path)
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
