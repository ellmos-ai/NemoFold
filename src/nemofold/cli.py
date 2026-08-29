from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from . import __version__
from .contracts import ActionMode, JobEnvelope, PrivacyMode, RunReport
from .demo import DeterministicDemoReasoner
from .demo_pipeline import run_full_offline_demo
from .inventory import scan_root
from .ledger import RunLedger
from .nemoclaw_package import validate_job_package
from .policy import PolicyConfig, PolicyGate
from .runtime import LocalAgentRuntime


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
    parser.print_help()
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
