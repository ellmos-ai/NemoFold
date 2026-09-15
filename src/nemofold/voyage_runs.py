"""Run a saved voyage as a chain and write one dossier over its steps.

The chain adds no authority of its own. Each step is the same job the strict
parser already accepted, run through the same gates, with its own ledger; the
dossier only links them and records what actually happened - including which
model really ran, which is never inferred from what the plan preferred.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .application import ExecutionConfig, run_job
from .artifacts import write_text_artifact
from .contracts import RunReport, RunStatus
from .inventory import scan_paths
from .job_io import load_job_snapshot, parse_job_payload
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
from .runtime import job_idempotency_key

VOYAGE_RUN_SCHEMA = "nemofold.voyage-run.v1"
MAX_CHAIN_STEPS = 24
ARTIFACT_HANDOFF_SCHEMA = "nemofold.artifact-handoff.v1"


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
    handoff: dict[str, Any] | None = None


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


def voyage_run_payload(
    result: VoyageRunResult,
    voyage: dict[str, Any],
    *,
    model_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the same bounded chain result to CLI, MCP and the web surface."""
    return {
        "ok": result.completed,
        "status": result.status,
        "run_id": result.run_id,
        "stopped_at": result.stopped_at,
        "dossier_path": result.dossier_path,
        "model_authority": voyage.get("model_authority", AUTHORITY_LINKS_WIN),
        "authority_reason": voyage.get("authority_reason", ""),
        "run_level_override": (
            None
            if model_override is None
            else f"{model_override.get('provider')}:{model_override.get('model')}"
        ),
        "steps": [
            {
                "order": step.order,
                "workflow": step.workflow,
                "run_id": step.run_id,
                "status": step.status,
                "artifact_count": step.artifact_count,
                "ledger_path": step.ledger_path,
                "model_used": step.model_used,
                "model_note": step.model_note,
                "model_level": step.model_level,
                "rights": step.rights,
                "rights_level": step.rights_level,
                "policy_note": step.policy_note,
                "errors": list(step.errors),
                "handoff": step.handoff,
            }
            for step in result.steps
        ],
    }


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
        if step.handoff:
            lines.append(
                f"- handoff: {step.handoff['format']} from "
                f"{step.handoff['producer_run_id']} (SHA-256 {step.handoff['sha256']})"
            )
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


def _verified_handoff(
    report: RunReport,
    *,
    output_dir: str,
    artifact_format: str,
    privacy_mode: str,
) -> dict[str, str]:
    """Bind one producer artifact to the next input; never trust a directory.

    The producer's in-memory report declares the artifact, but its content can
    change before a consumer reads it. Verify both its location and current
    digest before making it an approved input root.
    """
    matches = [item for item in report.artifacts if item.format == artifact_format]
    if not matches:
        raise ValueError(f"handoff_format_missing:{artifact_format}")
    if len(matches) != 1:
        raise ValueError(f"handoff_format_ambiguous:{artifact_format}")
    artifact = matches[0]
    if artifact.status != "written":
        raise ValueError(f"handoff_artifact_not_written:{artifact_format}")
    path = Path(artifact.path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"handoff_artifact_unavailable:{artifact_format}")
    resolved = path.resolve()
    if not resolved.is_relative_to(Path(output_dir).resolve()):
        raise ValueError(f"handoff_artifact_outside_producer:{artifact_format}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"handoff_artifact_unreadable:{artifact_format}") from exc
    if digest.hexdigest() != artifact.sha256:
        raise ValueError(f"handoff_hash_mismatch:{artifact_format}")
    return {
        "schema": ARTIFACT_HANDOFF_SCHEMA,
        "producer_run_id": report.run_id,
        "producer_workflow": report.workflow,
        "format": artifact.format,
        "path": str(resolved),
        "sha256": artifact.sha256,
        "privacy_mode": privacy_mode,
        "status": "verified",
    }


def _selected_registry_sources(
    receipt: dict[str, str], report: RunReport, *, output_dir: str
) -> tuple[list[str], dict[str, Any]]:
    """Resolve selected registry rows back to unchanged original source files.

    The registry artifact alone holds source IDs, not file paths. A saved job
    snapshot supplies the paths and source hashes, and its idempotency key must
    match the producer report before any path is accepted.
    """
    try:
        registry = json.loads(Path(receipt["path"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("handoff_registry_unreadable") from exc
    if not isinstance(registry, dict) or registry.get("schema") != (
        "nemofold.document-registry.v1"
    ):
        raise ValueError("handoff_registry_schema_invalid")
    rows = registry.get("rows")
    skipped = registry.get("skipped_source_ids")
    if (
        not isinstance(rows, list)
        or not isinstance(skipped, list)
        or any(not isinstance(row, dict) or not isinstance(row.get("source_id"), str)
               for row in rows)
        or any(not isinstance(source_id, str) for source_id in skipped)
    ):
        raise ValueError("handoff_registry_selection_invalid")
    selected_ids = [row["source_id"] for row in rows]
    if not selected_ids:
        raise ValueError("handoff_selection_empty")
    if len(set(selected_ids)) != len(selected_ids) or len(set(skipped)) != len(skipped):
        raise ValueError("handoff_registry_selection_invalid")

    snapshot_path = Path(output_dir) / "jobs" / f"{report.run_id}.json"
    try:
        snapshot = load_job_snapshot(snapshot_path)
    except ValueError as exc:
        raise ValueError("handoff_producer_snapshot_invalid") from exc
    if (
        snapshot.workflow != "document_registry"
        or job_idempotency_key(snapshot) != report.idempotency_key
        or not snapshot.parameters.get("topic_filter")
    ):
        raise ValueError("handoff_producer_snapshot_mismatch")
    sources = {source.source_id: source for source in snapshot.sources}
    if (
        len(sources) != len(snapshot.sources)
        or set(selected_ids) & set(skipped)
        or set(selected_ids) | set(skipped) != set(sources)
    ):
        raise ValueError("handoff_registry_selection_incomplete")

    roots = [Path(root).resolve() for root in snapshot.input_roots]
    paths: list[str] = []
    source_hashes: dict[str, str] = {}
    for source_id in selected_ids:
        source = sources[source_id]
        path = Path(source.path)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"handoff_source_unavailable:{source_id}")
        resolved = path.resolve()
        if not any(
            (root.is_dir() and resolved.is_relative_to(root))
            or (root.is_file() and resolved == root)
            for root in roots
        ):
            raise ValueError(f"handoff_source_outside_producer:{source_id}")
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise ValueError(f"handoff_source_unreadable:{source_id}") from exc
        if digest.hexdigest() != source.sha256:
            raise ValueError(f"handoff_source_hash_mismatch:{source_id}")
        paths.append(str(resolved))
        source_hashes[source_id] = source.sha256
    # The consumer inventories individual file roots, so its source IDs may
    # differ from the registry's folder-root IDs. Record the exact mapping
    # instead of making a later citation appear to refer to the producer ID.
    try:
        consumer_inventory = scan_paths(tuple(paths))
    except (OSError, ValueError) as exc:
        raise ValueError("handoff_consumer_inventory_unavailable") from exc
    producer_by_path = {
        path: source_id for path, source_id in zip(paths, selected_ids, strict=True)
    }
    lineage = []
    for item in consumer_inventory.records:
        producer_source_id = producer_by_path.get(item.path)
        if (
            producer_source_id is None
            or item.sha256 != source_hashes[producer_source_id]
            or item.extraction_status in {"unreadable", "excluded_symlink"}
        ):
            raise ValueError("handoff_consumer_source_mismatch")
        lineage.append(
            {
                "producer_source_id": producer_source_id,
                "consumer_source_id": item.source_id,
                "path": item.path,
                "sha256": item.sha256,
            }
        )
    return paths, {
        **receipt,
        "mode": "selected_sources",
        "selected_source_ids": selected_ids,
        "selected_source_sha256": source_hashes,
        "source_lineage": lineage,
        "topic_filter": list(snapshot.parameters["topic_filter"]),
    }


def _consumer_matches_lineage(
    receipt: dict[str, Any], report: RunReport, *, output_dir: str
) -> bool:
    """Reject a handoff whose actual consumer snapshot used different bytes.

    The source can change after the pre-run hash check. Even an idempotently
    reused consumer report is not proof that today's source bytes still match.
    """
    try:
        snapshot = load_job_snapshot(Path(output_dir) / "jobs" / f"{report.run_id}.json")
    except ValueError:
        return False
    if (
        snapshot.workflow != "synopsis_merge"
        or job_idempotency_key(snapshot) != report.idempotency_key
    ):
        return False
    expected = {
        item["path"]: (item["consumer_source_id"], item["sha256"])
        for item in receipt["source_lineage"]
    }
    if len(expected) != len(receipt["source_lineage"]) or len(snapshot.sources) != len(expected):
        return False
    for source in snapshot.sources:
        path = Path(source.path)
        if (
            expected.get(str(path.resolve())) != (source.source_id, source.sha256)
            or path.is_symlink()
            or not path.is_file()
        ):
            return False
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return False
        if digest.hexdigest() != source.sha256:
            return False
    return True


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
    if voyage.get("status", "runnable") != "runnable":
        raise ValueError("pending_capability voyage cannot run until its capability is ready")
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
    previous_report: RunReport | None = None
    previous_privacy_mode: str | None = None
    stopped_at: int | None = None
    blocked: ModelResolution | None = None
    for order, step in enumerate(steps, start=1):
        job_payload = dict(step["job"])
        step_run_id = f"{run_id}_{order:02d}"
        handoff_receipt: dict[str, Any] | None = None
        if step.get("reads_previous_output") and previous_output is not None:
            # Declared in the saved plan, applied here - never guessed.
            job_payload["input_roots"] = [previous_output]
        if step.get("handoff") is not None:
            spec = step["handoff"]
            artifact_format = spec.get("format") if isinstance(spec, dict) else None
            try:
                if not isinstance(artifact_format, str) or previous_report is None:
                    raise ValueError("handoff_previous_report_missing")
                handoff_receipt = _verified_handoff(
                    previous_report,
                    output_dir=previous_output or "",
                    artifact_format=artifact_format,
                    privacy_mode=previous_privacy_mode or "local_only",
                )
                if spec.get("mode") == "selected_sources":
                    job_payload["input_roots"], handoff_receipt = (
                        _selected_registry_sources(
                            handoff_receipt,
                            previous_report,
                            output_dir=previous_output or "",
                        )
                    )
            except ValueError as exc:
                rights, rights_level = resolve_rights(step.get("rights"), chain_rights)
                results.append(
                    VoyageStepResult(
                        order=order,
                        workflow=str(job_payload["workflow"]),
                        run_id=step_run_id,
                        status="handoff_blocked",
                        ledger_path=None,
                        artifact_count=0,
                        output_dir=str(job_payload["output_dir"]),
                        model_used=LOCAL_CORE,
                        model_note="No model or consumer ran: the artifact handoff failed.",
                        model_level="default",
                        rights=rights,
                        rights_level=rights_level,
                        errors=(str(exc),),
                    )
                )
                stopped_at = order
                break
            if spec.get("mode") != "selected_sources":
                job_payload["input_roots"] = [handoff_receipt["path"]]
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
        status = report.status.value
        errors = tuple(report.errors)
        model_note = resolution.note
        if (
            report.status is RunStatus.EXECUTED
            and (step.get("handoff") or {}).get("mode") == "selected_sources"
            and handoff_receipt is not None
            and not _consumer_matches_lineage(
                handoff_receipt, report, output_dir=job.output_dir
            )
        ):
            status = "handoff_invalidated"
            errors = ("handoff_consumer_source_mismatch",)
            model_note = (
                f"{resolution.note} Consumer did run, but its source snapshot "
                "no longer matches the verified handoff; result rejected."
            ).strip()
            handoff_receipt = {
                **handoff_receipt,
                "status": "invalidated",
                "validation_error": errors[0],
            }
        results.append(
            VoyageStepResult(
                order=order,
                workflow=job.workflow,
                run_id=step_run_id,
                status=status,
                ledger_path=str(outcome.report_path) if outcome.report_path else None,
                artifact_count=len(report.artifacts),
                output_dir=job.output_dir,
                model_used=resolution.model,
                model_note=model_note,
                model_level=resolution.level,
                rights=rights,
                rights_level=rights_level,
                policy_note=policy_note,
                errors=errors,
                handoff=handoff_receipt,
            )
        )
        previous_output = job.output_dir
        previous_report = report
        previous_privacy_mode = job.privacy_mode.value
        if report.status is not RunStatus.EXECUTED or status == "handoff_invalidated":
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
                "handoff": item.handoff,
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
