from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from . import __version__
from .application import (
    ExecutionConfig,
    prepare_nemoclaw_package,
    preview_job,
    resume_job,
    run_job,
    undo_run,
)
from .contracts import ActionMode, JobEnvelope, PrivacyMode, RunReport, RunStatus
from .demo import DeterministicDemoReasoner
from .demo_pipeline import run_full_offline_demo
from .drafts import DraftStore
from .inventory import scan_root
from .job_io import JobFileError, load_job_file, load_job_snapshot
from .ledger import RunLedger, validate_run_id
from .live_result import validate_result_package
from .nebius_token_factory import (
    TokenFactoryConfig,
    preflight_token_factory_package,
    run_token_factory_package,
)
from .nemoclaw_package import TRANSFER_ATTEMPT_FILENAME, validate_job_package
from .policy import PolicyConfig, PolicyGate
from .provider_analysis import analyze_with_provider
from .providers import PROVIDER_DESCRIPTORS, provider_capabilities, provider_config_from_mapping
from .report_verifier import verify_run_report
from .runtime import LocalAgentRuntime
from .webapp import WebAppConfig, build_server, serve_forever


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nemofold",
        description="Private, evidence-first document agent",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")
    demo = commands.add_parser("demo", help="run the synthetic offline evidence demo")
    demo.add_argument("--input", required=True, help="synthetic input folder")
    demo.add_argument("--output", required=True, help="local evidence output folder")
    demo.add_argument("--run-id", default="demo_offline")
    demo.add_argument(
        "--scenario",
        choices=("normal", "blocked-external"),
        default="normal",
    )
    verify_job = commands.add_parser("verify-job", help="validate a NemoClaw job package")
    verify_job.add_argument("path")
    verify_result = commands.add_parser(
        "verify-result", help="validate a live Token Factory result and its package"
    )
    verify_result.add_argument("path")
    token_factory_preflight = commands.add_parser(
        "token-factory-preflight",
        help="check a Token Factory package and cost bound without network access",
    )
    token_factory_preflight.add_argument("path")
    token_factory_preflight.add_argument("--input-price-usd-per-million", type=float, required=True)
    token_factory_preflight.add_argument(
        "--output-price-usd-per-million", type=float, required=True
    )
    token_factory_preflight.add_argument("--max-completion-tokens", type=int, default=1200)
    token_factory_preflight.add_argument("--timeout-seconds", type=float, default=60.0)
    token_factory_preflight.add_argument(
        "--base-url", default="https://api.tokenfactory.nebius.com/v1"
    )
    token_factory = commands.add_parser(
        "token-factory-run",
        help="execute one explicitly approved NemoClaw package on Nebius Token Factory",
    )
    token_factory.add_argument("path")
    token_factory.add_argument("--approve-live-transfer", action="store_true")
    token_factory.add_argument("--input-price-usd-per-million", type=float, required=True)
    token_factory.add_argument("--output-price-usd-per-million", type=float, required=True)
    token_factory.add_argument("--max-completion-tokens", type=int, default=1200)
    token_factory.add_argument("--timeout-seconds", type=float, default=60.0)
    token_factory.add_argument("--base-url", default="https://api.tokenfactory.nebius.com/v1")
    token_factory.add_argument(
        "--declared-nemoclaw-version",
        help="optional runtime metadata; never treated as NemoClaw proof",
    )
    package = commands.add_parser(
        "package", help="build a gated, local NemoClaw job package without uploading it"
    )
    package.add_argument("--job", required=True)
    package.add_argument("--allow-root", action="append", required=True)
    package.add_argument("--run-id", required=True)
    package.add_argument("--allow-external-models", action="store_true")
    package.add_argument("--max-external-cost-usd", type=float, default=0.0)
    for name, help_text in (
        ("preview", "validate and preview a local job without executing its workflow"),
        ("run", "execute a validated local job"),
    ):
        job_command = commands.add_parser(name, help=help_text)
        job_command.add_argument("--job", required=True)
        job_command.add_argument("--allow-root", action="append", required=True)
        job_command.add_argument("--run-id", required=True)
        job_command.add_argument("--allow-external-models", action="store_true")
        job_command.add_argument("--max-external-cost-usd", type=float, default=0.0)
        job_command.add_argument("--approve-actions", action="store_true")
    verify = commands.add_parser("verify", help="verify a local RunReport and its artifacts")
    verify.add_argument("path")
    resume = commands.add_parser("resume", help="resume a stored blocked or failed run")
    resume.add_argument("run_id")
    resume.add_argument("--output", required=True)
    resume.add_argument("--allow-root", action="append", required=True)
    resume.add_argument("--allow-external-models", action="store_true")
    resume.add_argument("--max-external-cost-usd", type=float, default=0.0)
    resume.add_argument("--approve-actions", action="store_true")
    undo = commands.add_parser("undo", help="undo a completed reversible action run")
    undo.add_argument("run_id")
    undo.add_argument("--output", required=True)
    undo.add_argument("--allow-root", action="append", required=True)
    undo.add_argument("--approve-actions", action="store_true")
    serve = commands.add_parser("serve", help="start the local NemoFold product console")
    serve.add_argument("--allow-root", action="append", required=True)
    serve.add_argument("--base-dir", default=".")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--allow-external-models", action="store_true")
    serve.add_argument("--max-external-cost-usd", type=float, default=0.0)
    serve.add_argument("--approve-actions", action="store_true")
    serve.add_argument("--expose-network", action="store_true")
    serve_demo = commands.add_parser(
        "serve-demo",
        help="start the bounded synthetic-only public demo console",
    )
    serve_demo.add_argument("--demo-root", required=True)
    serve_demo.add_argument("--host", default="127.0.0.1")
    serve_demo.add_argument("--port", type=int, default=8765)
    serve_demo.add_argument("--expose-network", action="store_true")
    serve_demo.add_argument("--max-parallel-jobs", type=int, default=4)
    providers = commands.add_parser(
        "providers",
        help="list the provider-neutral model adapters and their transfer classes",
    )
    providers.set_defaults(command="providers")
    provider_run = commands.add_parser(
        "analyze-provider",
        help="run an anonymized evidence job through a selected model provider",
    )
    provider_run.add_argument("--job", required=True)
    provider_run.add_argument("--allow-root", action="append", required=True)
    provider_run.add_argument("--run-id", required=True)
    provider_run.add_argument("--provider", choices=tuple(PROVIDER_DESCRIPTORS), required=True)
    provider_run.add_argument("--model", required=True)
    provider_run.add_argument("--base-url")
    provider_run.add_argument("--max-output-tokens", type=int, default=1200)
    provider_run.add_argument("--timeout-seconds", type=float, default=60.0)
    provider_run.add_argument("--executable")
    provider_run.add_argument("--allow-external-models", action="store_true")
    provider_run.add_argument("--approve-external-transfer", action="store_true")
    provider_run.add_argument("--max-external-cost-usd", type=float, default=0.0)
    draft_save = commands.add_parser(
        "draft-save",
        help="save a validated job for browser review without persisting approvals",
    )
    draft_save.add_argument("--job", required=True)
    draft_save.add_argument("--allow-root", action="append", required=True)
    draft_save.add_argument("--base-dir", default=".")
    draft_save.add_argument("--name")
    draft_save.add_argument("--provider", choices=tuple(PROVIDER_DESCRIPTORS))
    draft_save.add_argument("--model")
    draft_save.add_argument("--max-output-tokens", type=int, default=32_768)
    draft_save.add_argument("--timeout-seconds", type=float, default=1_800)
    draft_list = commands.add_parser("draft-list", help="list jobs waiting for browser review")
    draft_list.add_argument("--allow-root", action="append", required=True)
    draft_list.add_argument("--base-dir", default=".")
    mcp = commands.add_parser("mcp", help="start the bounded NemoFold MCP server over stdio")
    mcp.add_argument("--allow-root", action="append", required=True)
    mcp.add_argument("--base-dir", default=".")
    mcp.add_argument("--allow-external-models", action="store_true")
    mcp.add_argument("--max-external-cost-usd", type=float, default=0.0)
    mcp.add_argument("--approve-actions", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "demo":
        return _run_demo(args)
    if args.command == "verify-job":
        validation = validate_job_package(args.path)
        print(
            json.dumps(
                {
                    "valid": validation.valid,
                    "run_id": validation.run_id,
                    "errors": list(validation.errors),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if validation.valid else 2
    if args.command == "verify-result":
        result_validation = validate_result_package(args.path)
        print(
            json.dumps(
                {
                    "valid": result_validation.valid,
                    "run_id": result_validation.run_id,
                    "status": result_validation.status,
                    "errors": list(result_validation.errors),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if result_validation.valid else 2
    if args.command == "token-factory-preflight":
        return _token_factory_preflight_command(args)
    if args.command == "token-factory-run":
        return _token_factory_run_command(args)
    if args.command == "package":
        return _package_job_command(args)
    if args.command in {"preview", "run"}:
        return _run_job_command(args)
    if args.command == "verify":
        verification = verify_run_report(args.path)
        print(
            json.dumps(
                {
                    "valid": verification.valid,
                    "run_id": verification.run_id,
                    "errors": list(verification.errors),
                    "checked_artifacts": verification.checked_artifacts,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if verification.valid else 2
    if args.command == "resume":
        return _resume_job_command(args)
    if args.command == "undo":
        return _undo_job_command(args)
    if args.command == "serve":
        return _serve_command(args)
    if args.command == "serve-demo":
        return _serve_demo_command(args)
    if args.command == "providers":
        print(json.dumps({"providers": provider_capabilities()}, indent=2, sort_keys=True))
        return 0
    if args.command == "analyze-provider":
        return _provider_analysis_command(args)
    if args.command in {"draft-save", "draft-list"}:
        return _draft_command(args)
    if args.command == "mcp":
        return _mcp_command(args)
    parser.print_help()
    return 0


def _token_factory_preflight_command(args: argparse.Namespace) -> int:
    api_key = os.environ.get("NEBIUS_API_KEY", "")
    try:
        report = preflight_token_factory_package(
            args.path,
            TokenFactoryConfig(
                api_key=api_key or "preflight-only-placeholder",
                input_price_usd_per_million=args.input_price_usd_per_million,
                output_price_usd_per_million=args.output_price_usd_per_million,
                max_completion_tokens=args.max_completion_tokens,
                timeout_seconds=args.timeout_seconds,
                base_url=args.base_url,
            ),
            api_key_present=bool(api_key.strip()),
        )
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema": "nemofold.token-factory-preflight.v1",
                    "local_preflight_passed": False,
                    "network_called": False,
                    "transfer_performed": False,
                    "cloud_proof": False,
                    "errors": [str(exc)],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["local_preflight_passed"] else 2


def _token_factory_run_command(args: argparse.Namespace) -> int:
    api_key = os.environ.get("NEBIUS_API_KEY", "")
    try:
        result_path = run_token_factory_package(
            args.path,
            TokenFactoryConfig(
                api_key=api_key,
                input_price_usd_per_million=args.input_price_usd_per_million,
                output_price_usd_per_million=args.output_price_usd_per_million,
                max_completion_tokens=args.max_completion_tokens,
                timeout_seconds=args.timeout_seconds,
                base_url=args.base_url,
                declared_nemoclaw_version=args.declared_nemoclaw_version,
            ),
            approve_live_transfer=args.approve_live_transfer,
        )
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        validation = validate_result_package(args.path)
    except (FileExistsError, OSError, PermissionError, RuntimeError, ValueError) as exc:
        result_path = Path(args.path) / "result.json"
        attempt_path = Path(args.path) / TRANSFER_ATTEMPT_FILENAME
        transfer_performed: bool | None = False
        attempt_status = None
        if attempt_path.is_file() and not attempt_path.is_symlink():
            transfer_performed = None
            try:
                attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                attempt_status = "unreadable"
            else:
                if isinstance(attempt, dict):
                    attempt_status = attempt.get("status")
        if result_path.is_file() and not result_path.is_symlink():
            try:
                existing_result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
            else:
                if (
                    isinstance(existing_result, dict)
                    and existing_result.get("transfer_performed") is True
                ):
                    transfer_performed = True
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "errors": [str(exc)],
                    "attempt_status": attempt_status,
                    "transfer_performed": transfer_performed,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    runtime = payload.get("runtime_evidence", {})
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "result_path": str(result_path),
                "model_id": payload.get("model_id"),
                "transfer_performed": payload.get("transfer_performed"),
                "cloud_proof": payload.get("cloud_proof"),
                "usage": payload.get("usage"),
                "estimated_cost_usd": runtime.get("estimated_cost_usd"),
                "result_valid": validation.valid,
                "validation_errors": list(validation.errors),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if validation.valid and payload.get("status") == "executed" else 2


def _run_job_command(args: argparse.Namespace) -> int:
    try:
        loaded = load_job_file(args.job)
    except JobFileError as exc:
        print(json.dumps({"status": "blocked", "errors": [str(exc)]}, indent=2))
        return 2
    config = ExecutionConfig(
        allowed_roots=tuple(args.allow_root),
        external_models_allowed=args.allow_external_models,
        max_external_cost_usd=args.max_external_cost_usd,
        apply_actions_allowed=args.approve_actions,
    )
    try:
        result = (
            preview_job(loaded.job, config, run_id=args.run_id)
            if args.command == "preview"
            else run_job(loaded.job, config, run_id=args.run_id)
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "errors": [str(exc)]}, indent=2))
        return 2
    report = result.report
    _print_job_result(result)
    return 0 if report.status in {RunStatus.PLANNED, RunStatus.EXECUTED} else 2


def _package_job_command(args: argparse.Namespace) -> int:
    try:
        loaded = load_job_file(args.job)
        package = prepare_nemoclaw_package(
            loaded.job,
            ExecutionConfig(
                allowed_roots=tuple(args.allow_root),
                external_models_allowed=args.allow_external_models,
                max_external_cost_usd=args.max_external_cost_usd,
            ),
            run_id=args.run_id,
        )
    except (JobFileError, OSError, PermissionError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "errors": [str(exc)]}, indent=2))
        return 2
    print(
        json.dumps(
            {
                "status": "packaged",
                "run_id": package.run_id,
                "package_path": str(package.path),
                "manifest_sha256": package.manifest_sha256,
                "transfer_performed": False,
                "cloud_proof": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _provider_analysis_command(args: argparse.Namespace) -> int:
    try:
        loaded = load_job_file(args.job)
        provider = provider_config_from_mapping(
            {
                "provider_id": args.provider,
                "model": args.model,
                "base_url": args.base_url,
                "max_output_tokens": args.max_output_tokens,
                "timeout_seconds": args.timeout_seconds,
                "executable": args.executable,
            },
            allow_runtime_overrides=True,
        )
        result = analyze_with_provider(
            loaded.job,
            ExecutionConfig(
                allowed_roots=tuple(args.allow_root),
                external_models_allowed=args.allow_external_models,
                max_external_cost_usd=args.max_external_cost_usd,
            ),
            provider,
            run_id=args.run_id,
            approve_external_transfer=args.approve_external_transfer,
        )
    except (JobFileError, OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "errors": [str(exc)]}, indent=2))
        return 2
    report = result.report
    print(
        json.dumps(
            {
                "run_id": report.run_id,
                "workflow": report.workflow,
                "status": report.status.value,
                "errors": list(report.errors),
                "provider": report.metadata.get("provider"),
                "transfer_performed": report.metadata.get("transfer_performed"),
                "provider_execution_proof": bool(
                    report.metadata.get("provider_execution_proof", False)
                ),
                "competition_proof": False,
                "cloud_proof": False,
                "report_path": str(result.report_path) if result.report_path else None,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report.status is RunStatus.EXECUTED else 2


def _draft_command(args: argparse.Namespace) -> int:
    try:
        store = DraftStore(Path(args.base_dir), tuple(args.allow_root))
        if args.command == "draft-list":
            payload: dict[str, object] = {"drafts": store.list()}
        else:
            if bool(args.provider) != bool(args.model):
                raise ValueError("--provider and --model must be supplied together")
            load_job_file(args.job)
            job_value = json.loads(Path(args.job).read_text(encoding="utf-8"))
            provider = (
                {
                    "provider_id": args.provider,
                    "model": args.model,
                    "max_output_tokens": args.max_output_tokens,
                    "timeout_seconds": args.timeout_seconds,
                }
                if args.provider
                else None
            )
            payload = {
                "draft": store.save(
                    job_value,
                    provider=provider,
                    name=args.name,
                    source="cli",
                )
            }
    except (JobFileError, OSError, PermissionError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "errors": [str(exc)]}, indent=2))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _mcp_command(args: argparse.Namespace) -> int:
    from .mcp_server import MCPServerConfig, run_stdio_server

    try:
        run_stdio_server(
            MCPServerConfig(
                base_dir=Path(args.base_dir),
                execution=ExecutionConfig(
                    allowed_roots=tuple(args.allow_root),
                    external_models_allowed=args.allow_external_models,
                    max_external_cost_usd=args.max_external_cost_usd,
                    apply_actions_allowed=args.approve_actions,
                ),
            )
        )
    except (ImportError, OSError, PermissionError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "errors": [str(exc)]}, indent=2))
        return 2
    return 0


def _print_job_result(result) -> None:
    report = result.report
    print(
        json.dumps(
            {
                "run_id": report.run_id,
                "workflow": report.workflow,
                "status": report.status.value,
                "errors": list(report.errors),
                "cloud_proof": bool(report.metadata.get("cloud_proof", False)),
                "source_count": int(report.metadata.get("source_count", 0)),
                "report_path": str(result.report_path) if result.report_path else None,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _resume_job_command(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    try:
        validate_run_id(args.run_id)
        snapshot_path = output / "jobs" / f"{args.run_id}.json"
        job = load_job_snapshot(snapshot_path)
        if Path(job.output_dir).resolve() != output:
            raise JobFileError("snapshot output does not match --output")
        result = resume_job(
            job,
            ExecutionConfig(
                allowed_roots=tuple(args.allow_root),
                external_models_allowed=args.allow_external_models,
                max_external_cost_usd=args.max_external_cost_usd,
                apply_actions_allowed=args.approve_actions,
            ),
            run_id=args.run_id,
        )
    except (JobFileError, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "errors": [str(exc)]}, indent=2))
        return 2
    _print_job_result(result)
    return 0 if result.report.status is RunStatus.EXECUTED else 2


def _undo_job_command(args: argparse.Namespace) -> int:
    try:
        result = undo_run(
            args.output,
            ExecutionConfig(
                allowed_roots=tuple(args.allow_root),
                apply_actions_allowed=args.approve_actions,
            ),
            run_id=args.run_id,
        )
    except (OSError, PermissionError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "errors": [str(exc)]}, indent=2))
        return 2
    _print_job_result(result)
    return 0 if result.report.status is RunStatus.EXECUTED else 2


def _serve_command(args: argparse.Namespace) -> int:
    try:
        server = build_server(
            WebAppConfig(
                base_dir=Path(args.base_dir),
                execution=ExecutionConfig(
                    allowed_roots=tuple(args.allow_root),
                    external_models_allowed=args.allow_external_models,
                    max_external_cost_usd=args.max_external_cost_usd,
                    apply_actions_allowed=args.approve_actions,
                ),
                exposed_to_network=args.expose_network,
            ),
            host=args.host,
            port=args.port,
        )
    except (OSError, PermissionError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "errors": [str(exc)]}, indent=2))
        return 2
    host_value, port = server.server_address[:2]
    host = host_value.decode() if isinstance(host_value, bytes) else str(host_value)
    print(
        json.dumps(
            {
                "status": "serving",
                "url": f"http://{host}:{port}/",
                "network_exposed": args.expose_network,
                "cloud_proof": False,
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        serve_forever(server)
    except KeyboardInterrupt:
        return 0
    return 0


def _serve_demo_command(args: argparse.Namespace) -> int:
    demo_root = Path(args.demo_root)
    try:
        server = build_server(
            WebAppConfig(
                base_dir=demo_root.parent,
                execution=ExecutionConfig(allowed_roots=(str(demo_root),)),
                exposed_to_network=args.expose_network,
                public_demo=True,
                demo_source_root=demo_root,
                max_parallel_jobs=args.max_parallel_jobs,
            ),
            host=args.host,
            port=args.port,
        )
    except (OSError, PermissionError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "errors": [str(exc)]}, indent=2))
        return 2
    host_value, port = server.server_address[:2]
    host = host_value.decode() if isinstance(host_value, bytes) else str(host_value)
    print(
        json.dumps(
            {
                "status": "serving",
                "url": f"http://{host}:{port}/",
                "network_exposed": args.expose_network,
                "public_demo": True,
                "synthetic_only": True,
                "cloud_proof": False,
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        serve_forever(server)
    except KeyboardInterrupt:
        return 0
    return 0


def _run_demo(args: argparse.Namespace) -> int:
    input_root = Path(args.input).resolve()
    output_root = Path(args.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if args.scenario == "normal":
        report = run_full_offline_demo(input_root, output_root, run_id=args.run_id)
        _print_demo_summary(report, output_root)
        return 0

    inventory = scan_root(input_root)
    job = JobEnvelope(
        workflow="platform_proof",
        input_roots=(str(input_root),),
        output_dir=str(output_root),
        questions=("When does the current synthetic policy begin?",),
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        action_mode=ActionMode.DRY_RUN,
        model_id="nvidia/nemotron",
        model_budget_usd=1.0,
        sources=inventory.records,
    )
    ledger = RunLedger(output_root / "ledger")
    runtime = LocalAgentRuntime(
        gate=PolicyGate(
            PolicyConfig(
                allowed_roots=(str(input_root), str(output_root)),
                external_models_allowed=True,
                max_external_cost_usd=1.0,
            )
        ),
        ledger=ledger,
    )
    result = runtime.execute(
        job,
        DeterministicDemoReasoner(),
        {},
        run_id=args.run_id,
    )
    report = result.report
    report = replace(
        report,
        metadata={**report.metadata, "cloud_proof": False, "scenario": args.scenario},
    )
    ledger.update(report)
    _print_demo_summary(report, output_root)
    return 2


def _print_demo_summary(report: RunReport, output_root: Path) -> None:
    print(
        json.dumps(
            {
                "run_id": report.run_id,
                "status": report.status.value,
                "errors": list(report.errors),
                "cloud_proof": False,
                "report_path": str(output_root / "ledger" / f"{report.run_id}.json"),
            },
            indent=2,
            sort_keys=True,
        )
    )
