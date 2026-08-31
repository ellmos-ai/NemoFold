from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import nemofold.cli as cli_module
import nemofold.webapp as webapp_module
from nemofold.application import ExecutionConfig, JobCommandResult
from nemofold.cli import build_parser, main
from nemofold.contracts import RunReport, RunStatus
from nemofold.webapp import WebAppConfig, build_server


@contextmanager
def running_provider_server(tmp_path):
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


@contextmanager
def running_external_provider_server(tmp_path):
    server = build_server(
        WebAppConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(
                allowed_roots=(str(tmp_path),),
                external_models_allowed=True,
            ),
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


@contextmanager
def running_network_exposed_server(tmp_path):
    server = build_server(
        WebAppConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
            exposed_to_network=True,
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


def write_job(tmp_path: Path) -> Path:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "case.txt").write_text("Evidence.", encoding="utf-8")
    path = tmp_path / "job.json"
    path.write_text(
        json.dumps(
            {
                "schema": "nemofold.job.v1",
                "workflow": "evidence_analyst",
                "input_roots": ["documents"],
                "output_dir": "output",
                "questions": ["What is supported?"],
                "privacy_mode": "local_only",
                "action_mode": "dry_run",
                "parameters": {},
            }
        ),
        encoding="utf-8",
    )
    return path


def executed_result(job, provider, run_id):
    return JobCommandResult(
        RunReport(
            run_id=run_id,
            idempotency_key="provider-test",
            workflow=job.workflow,
            status=RunStatus.EXECUTED,
            metadata={
                "provider": provider.public_summary(),
                "transfer_performed": False,
                "provider_execution_proof": True,
                "competition_proof": False,
                "cloud_proof": False,
            },
        ),
        Path(job.output_dir) / "ledger" / f"{run_id}.json",
    )


def test_cli_exposes_provider_and_mcp_commands_without_mixing_nebius(capsys) -> None:
    assert main(["providers"]) == 0
    payload = json.loads(capsys.readouterr().out)
    ids = {item["provider_id"] for item in payload["providers"]}

    assert ids == {
        "ollama",
        "lm-studio",
        "codex-cli",
        "claude-code",
        "openai",
        "anthropic",
    }
    assert "nebius" not in ids
    parsed = build_parser().parse_args(["mcp", "--allow-root", "C:/documents"])
    assert parsed.command == "mcp"


def test_cli_provider_analysis_routes_through_the_shared_service(
    tmp_path, capsys, monkeypatch
) -> None:
    job_path = write_job(tmp_path)
    captured = {}

    def fake_analyze(job, execution, provider, *, run_id, approve_external_transfer):
        captured.update(
            {
                "job": job,
                "execution": execution,
                "provider": provider,
                "run_id": run_id,
                "approval": approve_external_transfer,
            }
        )
        return executed_result(job, provider, run_id)

    monkeypatch.setattr(cli_module, "analyze_with_provider", fake_analyze)

    exit_code = main(
        [
            "analyze-provider",
            "--job",
            str(job_path),
            "--allow-root",
            str(tmp_path),
            "--run-id",
            "cli_provider",
            "--provider",
            "ollama",
            "--model",
            "qwen3",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured["provider"].provider_id == "ollama"
    assert captured["approval"] is False
    assert result["provider_execution_proof"] is True
    assert result["competition_proof"] is False


def test_loopback_api_lists_and_executes_provider_surface(tmp_path, monkeypatch) -> None:
    job_path = write_job(tmp_path)
    job = json.loads(job_path.read_text(encoding="utf-8"))

    def fake_analyze(parsed, execution, provider, *, run_id, approve_external_transfer):
        assert provider.provider_id == "lm-studio"
        assert approve_external_transfer is False
        return executed_result(parsed, provider, run_id)

    monkeypatch.setattr(webapp_module, "analyze_with_provider", fake_analyze)

    with running_provider_server(tmp_path) as base_url:
        with urlopen(base_url + "/api/status", timeout=5) as response:  # noqa: S310
            status = json.load(response)
        request = Request(
            base_url + "/api/provider-analyze",
            data=json.dumps(
                {
                    "run_id": "api_provider",
                    "job": job,
                    "provider": {"provider_id": "lm-studio", "model": "local-model"},
                    "approve_external_transfer": False,
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:  # noqa: S310
            result = json.load(response)

    assert status["provider_surface_enabled"] is True
    assert status["provider_runtime_ready"] is False
    assert status["external_models_allowed"] is False
    assert {item["provider_id"] for item in status["providers"]} >= {
        "ollama",
        "openai",
        "anthropic",
    }
    assert result["ok"] is True
    assert result["report"]["metadata"]["competition_proof"] is False


def test_loopback_status_exposes_external_server_gate_without_claiming_runtime(tmp_path) -> None:
    with (
        running_external_provider_server(tmp_path) as base_url,
        urlopen(base_url + "/api/status", timeout=5) as response,  # noqa: S310
    ):
        status = json.load(response)

    assert status["provider_surface_enabled"] is True
    assert status["external_models_allowed"] is True
    assert status["provider_runtime_ready"] is False
    assert {item["provider_id"] for item in status["providers"] if item["external_transfer"]} == {
        "anthropic",
        "claude-code",
        "codex-cli",
        "openai",
    }


def test_network_exposed_http_server_disables_provider_surface(tmp_path) -> None:
    job_path = write_job(tmp_path)
    job = json.loads(job_path.read_text(encoding="utf-8"))

    with running_network_exposed_server(tmp_path) as base_url:
        with urlopen(base_url + "/api/status", timeout=5) as response:  # noqa: S310
            status = json.load(response)
        request = Request(
            base_url + "/api/provider-analyze",
            data=json.dumps(
                {
                    "run_id": "network_provider",
                    "job": job,
                    "provider": {"provider_id": "ollama", "model": "qwen3"},
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=5)  # noqa: S310

    assert caught.value.code == 403
    assert status["provider_surface_enabled"] is False
    assert status["provider_runtime_ready"] is False
    assert status["external_models_allowed"] is False
    assert status["providers"] == []
