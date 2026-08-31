"""Run a saved voyage as a chain and write one dossier over its steps.

The chain adds no authority of its own. Each step is the same job the strict
parser already accepted, run through the same gates, with its own ledger; the
dossier only links them and records what actually happened - including which
model really ran, which is never inferred from what the plan preferred.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .application import ExecutionConfig, run_job
from .artifacts import write_text_artifact
from .contracts import RunStatus
from .job_io import parse_job_payload
from .voyages import LOCAL_ONLY

VOYAGE_RUN_SCHEMA = "nemofold.voyage-run.v1"
LOCAL_CORE = "nemofold-local-core"
MAX_CHAIN_STEPS = 24


@dataclass(frozen=True, slots=True)
class VoyageStepResult:
    order: int
    workflow: str
    run_id: str
    status: str
    ledger_path: str | None
    artifact_count: int
    output_dir: str
    model_used: str
    model_note: str
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VoyageRunResult:
    voyage_id: str
    name: str
    run_id: str
    status: str
    steps: tuple[VoyageStepResult, ...]
    dossier_path: str
    stopped_at: int | None

    @property
    def completed(self) -> bool:
        return self.stopped_at is None


def resolve_model(model_pref: Any, *, external_allowed: bool) -> tuple[str, str]:
    """Say which model a chained step will actually use, and why.

    A chain never performs an external transfer on its own: that needs
    privacy_mode allow_once and a per-run approval, which a chain cannot grant
    on the user's behalf. So an external preference is answered by running the
    local core - a fallback that lowers exposure - and the note says so rather
    than letting the dossier imply the preferred model ran.
    """
    if not isinstance(model_pref, dict) or not model_pref:
        return LOCAL_CORE, "No model preference was stored; the local engine ran."
    preferred = model_pref.get("preferred", {})
    label = f"{preferred.get('provider')}:{preferred.get('model')}"
    fallback = model_pref.get("fallback", LOCAL_ONLY)
    if not external_allowed:
        note = (
            f"Preference {label} was not applied: a chained step performs no external "
            "transfer, which needs allow_once and a per-run approval. The local engine "
            "ran instead, which lowers exposure."
        )
        return LOCAL_CORE, note
    note = (
        f"Preference {label} is permitted by the server, but a chained step still runs "
        "locally: raising exposure is never automatic. "
        + (
            "The stored fallback is local-only."
            if fallback == LOCAL_ONLY
            else f"The stored fallback is {fallback.get('provider')}:{fallback.get('model')}."
        )
    )
    return LOCAL_CORE, note


def _dossier_markdown(result: VoyageRunResult) -> str:
    lines = [
        f"# Voyage dossier · {result.name}",
        "",
        f"Run {result.run_id} · status {result.status}",
        "",
    ]
    if result.stopped_at is not None:
        lines.extend(
            [
                f"The chain stopped at step {result.stopped_at}. Later steps were not "
                "started, so nothing downstream ran on an unfinished result.",
                "",
            ]
        )
    for step in result.steps:
        lines.extend(
            [
                f"## Step {step.order} · {step.workflow}",
                "",
                f"- run: {step.run_id}",
                f"- status: {step.status}",
                f"- artifacts: {step.artifact_count}",
                f"- ledger: {step.ledger_path or 'not written'}",
                f"- model: {step.model_used}",
                f"- model note: {step.model_note}",
            ]
        )
        if step.errors:
            lines.append(f"- errors: {', '.join(step.errors)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_voyage(
    voyage: dict[str, Any],
    config: ExecutionConfig,
    *,
    run_id: str,
    base_dir: str | Path = ".",
) -> VoyageRunResult:
    """Run the steps in order, handing output to input where the plan says so."""
    steps = voyage.get("steps") or []
    if not steps:
        raise ValueError("this voyage has no step to run")
    if len(steps) > MAX_CHAIN_STEPS:
        raise ValueError(f"a voyage chain may not exceed {MAX_CHAIN_STEPS} steps")

    results: list[VoyageStepResult] = []
    previous_output: str | None = None
    stopped_at: int | None = None
    for order, step in enumerate(steps, start=1):
        job_payload = dict(step["job"])
        if step.get("reads_previous_output") and previous_output is not None:
            # Declared in the saved plan, applied here - never guessed.
            job_payload["input_roots"] = [previous_output]
        job = parse_job_payload(job_payload, base_dir=base_dir)
        step_run_id = f"{run_id}_{order:02d}"
        model_used, model_note = resolve_model(
            step.get("model_pref"), external_allowed=config.external_models_allowed
        )
        outcome = run_job(job, config, run_id=step_run_id)
        report = outcome.report
        results.append(
            VoyageStepResult(
                order=order,
                workflow=job.workflow,
                run_id=step_run_id,
                status=report.status.value,
                ledger_path=str(outcome.report_path) if outcome.report_path else None,
                artifact_count=len(report.artifacts),
                output_dir=job.output_dir,
                model_used=model_used,
                model_note=model_note,
                errors=tuple(report.errors),
            )
        )
        previous_output = job.output_dir
        if report.status is not RunStatus.EXECUTED:
            stopped_at = order
            break

    status = "executed" if stopped_at is None else "stopped"
    dossier_dir = Path(str(steps[0]["job"]["output_dir"])).parent / "voyage-dossier"
    result = VoyageRunResult(
        voyage_id=str(voyage.get("voyage_id", "")),
        name=str(voyage.get("name", "")),
        run_id=run_id,
        status=status,
        steps=tuple(results),
        dossier_path=str(dossier_dir / f"{run_id}.json"),
        stopped_at=stopped_at,
    )
    payload = {
        "schema": VOYAGE_RUN_SCHEMA,
        "voyage_id": result.voyage_id,
        "name": result.name,
        "run_id": run_id,
        "status": status,
        "completed": result.completed,
        "stopped_at_step": stopped_at,
        "started_at": datetime.now(UTC).isoformat(),
        "cloud_proof": False,
        "steps": [
            {
                "order": item.order,
                "workflow": item.workflow,
                "run_id": item.run_id,
                "status": item.status,
                "ledger_path": item.ledger_path,
                "artifact_count": item.artifact_count,
                "output_dir": item.output_dir,
                "model_used": item.model_used,
                "model_note": item.model_note,
                "errors": list(item.errors),
            }
            for item in result.steps
        ],
    }
    write_text_artifact(
        dossier_dir / f"{run_id}.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        "voyage-dossier",
    )
    write_text_artifact(
        dossier_dir / f"{run_id}.md", _dossier_markdown(result), "voyage-dossier"
    )
    return result
