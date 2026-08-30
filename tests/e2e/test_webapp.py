from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nemofold.application import ExecutionConfig
from nemofold.cli import build_parser
from nemofold.webapp import WebAppConfig, build_server


@contextmanager
def running_server(tmp_path):
    server = build_server(
        WebAppConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
        ),
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def get_json(url: str) -> tuple[dict, object]:
    with urlopen(url, timeout=5) as response:  # noqa: S310 - loopback test server
        return json.load(response), response.headers


def post_json(url: str, payload: dict, *, origin: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=5) as response:  # noqa: S310 - loopback test server
        return json.load(response)


def test_web_console_serves_product_ui_and_executes_strict_preview(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "policy.txt").write_text(
        "Coverage begins on 1 April 2026.", encoding="utf-8"
    )
    job = {
        "schema": "nemofold.job.v1",
        "workflow": "evidence_analyst",
        "input_roots": ["documents"],
        "output_dir": "output",
        "questions": ["When does coverage begin?"],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {"max_chunks": 4, "formats": ["md"]},
    }

    with running_server(tmp_path) as base_url:
        with urlopen(base_url + "/", timeout=5) as response:  # noqa: S310
            html = response.read().decode()
            headers = response.headers
        status, _ = get_json(base_url + "/api/status")
        preview = post_json(
            base_url + "/api/preview",
            {"run_id": "web_preview", "job": job},
        )

    assert "Your files." in html
    assert 'id="targetRoots"' in html
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert status["cloud_proof"] is False
    assert status["live_runtime_ready"] is False
    assert len(status["workflows"]) == 8
    assert preview["ok"] is True
    assert preview["report"]["status"] == "planned"
    assert preview["report"]["coverage"]["read_sources"] == 1


def test_web_console_assets_expose_workflow_specific_defaults(tmp_path) -> None:
    with (
        running_server(tmp_path) as base_url,
        urlopen(base_url + "/assets/app.js", timeout=5) as response,  # noqa: S310
    ):
        script = response.read().decode()

    assert "workflowDefaults" in script
    assert "target_roots: lines" in script
    assert "evidence_level: \"offline\"" in script


def test_web_console_rejects_cross_origin_posts(tmp_path) -> None:
    with (
        running_server(tmp_path) as base_url,
        pytest.raises(HTTPError) as captured,
    ):
        post_json(
            base_url + "/api/preview",
            {"run_id": "cross_origin", "job": {}},
            origin="https://attacker.example",
        )

    assert captured.value.code == 403
    assert json.load(captured.value)["error"] == "origin_rejected"


def test_non_loopback_binding_requires_explicit_exposure(tmp_path) -> None:
    config = WebAppConfig(
        base_dir=tmp_path,
        execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
    )

    with pytest.raises(PermissionError, match="explicit network exposure"):
        build_server(config, host="0.0.0.0", port=0)


def test_web_console_action_gate_uses_the_shared_explicit_approval_name(tmp_path) -> None:
    args = build_parser().parse_args(
        ["serve", "--allow-root", str(tmp_path), "--approve-actions"]
    )

    assert args.approve_actions is True
