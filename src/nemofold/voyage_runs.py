"""Run a saved voyage as a chain and write one dossier over its steps.

The chain adds no authority of its own. Each step is the same job the strict
parser already accepted, run through the same gates, with its own ledger; the
dossier only links them and records what actually happened - including which
model really ran, which is never inferred from what the plan preferred.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .application import ExecutionConfig, run_job
from .artifacts import write_text_artifact
from .contracts import RunStatus
from .job_io import parse_job_payload
from .model_authority import (
    AUTHORITY_LINKS_WIN,
    LOCAL_CORE,
    ModelResolution,
    endpoint_label,
    is_external,
    resolve_authority,
    resolve_rights,
)
from .policies import PolicyStore, cleanup_rules_for_step
from .provider_analysis import PROVIDER_WORKFLOWS, analyze_with_provider
from .providers import ProviderConfig

VOYAGE_RUN_SCHEMA = "nemofold.voyage-run.v1"
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
    model_level: str
    rights: str
    rights_level: str
    policy_note: str = ""
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
    if result.status == "needs_user_input":
        lines.extend(
            [
                "A model setting conflicts with the chain's local-only cap. Exposure "
                "is never raised automatically, so this needs your decision.",
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
                f"- model: {step.model_used} (level: {step.model_level})",
                f"- model note: {step.model_note}",
                f"- outbound rights: {step.rights} (level: {step.rights_level})",
            ]
        )
        if step.policy_note:
            lines.append(f"- policy: {step.policy_note}")
        if step.errors:
            lines.append(f"- errors: {', '.join(step.errors)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _route_step(resolution: ModelResolution, workflow: str) -> ModelResolution:
    """Decide how a step actually reaches the model its plan names.

    Three outcomes, and the dossier has to be able to tell them apart:

    - a deterministic workflow has no reasoning worker at all, so a named model
      is a preference that cannot apply. Saying it ran would describe something
      that did not happen;
    - a local worker can run inside a chain, because a local endpoint needs no
      per-run transfer approval;
    - an external worker cannot. A chain never grants a per-run transfer
      approval - that is the standing rule, not a limitation of this function -
      so the step stops and asks instead of quietly running somewhere else.
    """
    if resolution.endpoint is None:
        return resolution
    if workflow not in PROVIDER_WORKFLOWS:
        return replace(
            resolution,
            model=LOCAL_CORE,
            note=(
                f"{resolution.model} was set at the {resolution.level} level, but "
                f"{workflow} is deterministic and uses no model. The preference is "
                "kept and applies to steps that do."
            ),
        )
    if is_external(resolution.endpoint):
        return replace(
            resolution,
            model=LOCAL_CORE,
            note=(
                f"{endpoint_label(resolution.endpoint)} sends content off this host, "
                "and a chain run never grants a per-run transfer approval. Run this "
                "step on its own to approve the transfer, or choose a local model."
            ),
            needs_user_input=True,
            conflict="chain_grants_no_transfer_approval",
        )
    return resolution


def run_voyage(
    voyage: dict[str, Any],
    config: ExecutionConfig,
    *,
    run_id: str,
    base_dir: str | Path = ".",
    model_override: dict[str, Any] | None = None,
    policy_store: PolicyStore | None = None,
) -> VoyageRunResult:
    """Run the steps in order, handing output to input where the plan says so.

    model_override applies to this run only. It never touches what is stored,
    and it does not lift the chain's local-only cap.
    """
    steps = voyage.get("steps") or []
    if not steps:
        raise ValueError("this voyage has no step to run")
    if len(steps) > MAX_CHAIN_STEPS:
        raise ValueError(f"a voyage chain may not exceed {MAX_CHAIN_STEPS} steps")

    voyage_id = str(voyage.get("voyage_id", ""))
    chain_pref = voyage.get("model_pref")
    authority = voyage.get("model_authority", AUTHORITY_LINKS_WIN)
    chain_rights = voyage.get("rights")
    results: list[VoyageStepResult] = []
    previous_output: str | None = None
    stopped_at: int | None = None
    blocked: ModelResolution | None = None
    for order, step in enumerate(steps, start=1):
        job_payload = dict(step["job"])
        if step.get("reads_previous_output") and previous_output is not None:
            # Declared in the saved plan, applied here - never guessed.
            job_payload["input_roots"] = [previous_output]
        policy_note = ""
        if policy_store is not None and job_payload.get("workflow") == "cleanup_rules":
            # A bound policy fills in only what the contract left empty, and the
            # dossier says which of the two decided.
            bound = (
                *policy_store.for_target(voyage_id),
                *policy_store.for_target(voyage_id, step_index=order),
            )
            parameters = dict(job_payload.get("parameters") or {})
            rules, origin = cleanup_rules_for_step(bound, parameters)
            if rules and not parameters.get("rules"):
                parameters["rules"] = rules
                job_payload["parameters"] = parameters
            policy_note = f"Cleanup rules came from {origin}."
        job = parse_job_payload(job_payload, base_dir=base_dir)
        step_run_id = f"{run_id}_{order:02d}"
        resolution = resolve_authority(
            step_pref=step.get("model_pref"),
            chain_pref=chain_pref,
            authority=authority,
            run_override=model_override,
        )
        resolution = _route_step(resolution, job.workflow)
        rights, rights_level = resolve_rights(step.get("rights"), chain_rights)
        if resolution.needs_user_input:
            # An unresolved exposure conflict stops the chain before the step
            # runs: neither escalating nor quietly downgrading is ours to pick.
            blocked = resolution
            results.append(
                VoyageStepResult(
                    order=order,
                    workflow=job.workflow,
                    run_id=step_run_id,
                    status="needs_user_input",
                    ledger_path=None,
                    artifact_count=0,
                    output_dir=job.output_dir,
                    model_used=resolution.model,
                    model_note=resolution.note,
                    model_level=resolution.level,
                    rights=rights,
                    rights_level=rights_level,
                    policy_note=policy_note,
                    errors=(resolution.conflict or "model_conflict",),
                )
            )
            stopped_at = order
            break
        # A named local worker is actually used, not merely reported.
        outcome = (
            analyze_with_provider(
                job,
                config,
                ProviderConfig(
                    provider_id=str(resolution.endpoint["provider"]),
                    model=str(resolution.endpoint["model"]),
                ),
                run_id=step_run_id,
                approve_external_transfer=False,
            )
            if resolution.endpoint is not None and job.workflow in PROVIDER_WORKFLOWS
            else run_job(job, config, run_id=step_run_id)
        )
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
                model_used=resolution.model,
                model_note=resolution.note,
                model_level=resolution.level,
                rights=rights,
                rights_level=rights_level,
                policy_note=policy_note,
                errors=tuple(report.errors),
            )
        )
        previous_output = job.output_dir
        if report.status is not RunStatus.EXECUTED:
            stopped_at = order
            break

    status = (
        "executed"
        if stopped_at is None
        else "needs_user_input"
        if blocked is not None
        else "stopped"
    )
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
        "model_authority": authority,
        "authority_reason": voyage.get("authority_reason", ""),
        "run_level_override": (
            None
            if model_override is None
            else f"{model_override.get('provider')}:{model_override.get('model')}"
        ),
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
                "model_level": item.model_level,
                "rights": item.rights,
                "rights_level": item.rights_level,
                "policy_note": item.policy_note,
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
