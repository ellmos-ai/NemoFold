from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .action_journal import ActionJournal
from .anonymizer import pseudonymize_questions_and_receipts
from .artifacts import write_text_artifact
from .bundle_export import create_text_bundle
from .contracts import (
    ActionMode,
    ArtifactRecord,
    Claim,
    Coverage,
    EvidenceLocator,
    GateDecision,
    JobEnvelope,
    PrivacyMode,
    RunReport,
    RunStatus,
    to_primitive,
)
from .document_extract import extract_document_text
from .document_index import DocumentIndex, SearchHit
from .evidence import compute_coverage, validate_claim
from .evidence_analyst import build_context_receipts
from .folder_digest import build_digest
from .inventory import InventoryResult, scan_paths
from .job_io import job_snapshot_payload, load_job_snapshot, validate_workflow_parameters
from .ledger import RunLedger, validate_run_id
from .nemoclaw_package import NemoClawPackage, export_job_package
from .policy import PolicyConfig, PolicyGate
from .report_studio import ReportDocument, render_report_formats
from .runtime import job_idempotency_key
from .smart_inbox import RoutingRule, plan_inbox
from .storage_policy import PolicyRule, PolicySet, StoragePlan, preview_storage
from .version_resolver import (
    VersionCandidate,
    compare_versions,
    infer_family_key,
    resolve_current,
)


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    allowed_roots: tuple[str, ...]
    external_models_allowed: bool = False
    max_external_cost_usd: float = 0.0
    apply_actions_allowed: bool = False


@dataclass(frozen=True, slots=True)
class JobCommandResult:
    report: RunReport
    report_path: Path | None


def prepare_nemoclaw_package(
    job: JobEnvelope,
    config: ExecutionConfig,
    *,
    run_id: str,
) -> NemoClawPackage:
    validate_run_id(run_id)
    validate_workflow_parameters(job)
    if job.workflow not in {"evidence_analyst", "platform_proof"}:
        raise ValueError("NemoClaw packages support only analysis workflows")
    gate = _gate(config)
    decision = gate.evaluate(job)
    if not decision.allowed:
        raise PermissionError(", ".join(decision.reasons))
    prepared, inventory = _prepare_inventory(job)
    texts = _read_text_sources(inventory)
    max_chunks = prepared.parameters.get("max_chunks", 8)
    if isinstance(max_chunks, bool) or not isinstance(max_chunks, int) or max_chunks < 1:
        raise ValueError("max_chunks must be a positive integer")
    index = DocumentIndex(Path(prepared.output_dir) / "index" / "nemofold.sqlite3")
    try:
        index.prune_sources(frozenset(texts))
        for source in inventory.records:
            text_value = texts.get(source.source_id)
            if text_value is not None:
                index.index_source(source, text_value)
        receipts = build_context_receipts(
            index,
            prepared.questions,
            hits_per_question=max_chunks,
        )
    finally:
        index.close()
    sensitive_terms = prepared.parameters.get("pseudonymize_terms", [])
    if not isinstance(sensitive_terms, list) or any(
        not isinstance(item, str) for item in sensitive_terms
    ):
        raise ValueError("pseudonymize_terms must be a list of strings")
    package = export_job_package(
        prepared,
        receipts,
        decision,
        Path(prepared.output_dir) / "nemoclaw-packages" / run_id,
        run_id=run_id,
        sensitive_terms=sensitive_terms,
    )
    write_text_artifact(
        Path(prepared.output_dir) / "gates" / f"{run_id}.json",
        json.dumps(
            {
                "schema": "nemofold.external-gate-record.v1",
                "run_id": run_id,
                "decision": to_primitive(decision),
                "package_manifest_sha256": package.manifest_sha256,
                "transfer_performed": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "external-gate-record",
    )
    return package


class WorkflowBlocked(RuntimeError):
    def __init__(
        self,
        errors: tuple[str, ...],
        *,
        actions: tuple[str, ...] = (),
        artifacts: tuple[ArtifactRecord, ...] = (),
        coverage: Coverage | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        super().__init__(", ".join(errors))
        self.errors = errors
        self.actions = actions
        self.artifacts = artifacts
        self.coverage = coverage
        self.metadata = metadata or {}


def _gate(config: ExecutionConfig) -> PolicyGate:
    return PolicyGate(
        PolicyConfig(
            allowed_roots=config.allowed_roots,
            external_models_allowed=config.external_models_allowed,
            max_external_cost_usd=config.max_external_cost_usd,
            apply_actions_allowed=config.apply_actions_allowed,
        )
    )


def _report_path(job: JobEnvelope, run_id: str) -> Path:
    return Path(job.output_dir) / "ledger" / f"{run_id}.json"


def _snapshot_path(job: JobEnvelope, run_id: str) -> Path:
    return Path(job.output_dir) / "jobs" / f"{run_id}.json"


def _write_snapshot(job: JobEnvelope, run_id: str) -> Path:
    path = _snapshot_path(job, run_id)
    write_text_artifact(
        path,
        json.dumps(job_snapshot_payload(job), indent=2, sort_keys=True) + "\n",
        "job-snapshot",
    )
    return path


def _save_if_output_allowed(
    job: JobEnvelope,
    report: RunReport,
    gate: PolicyGate,
) -> Path | None:
    if not gate.path_allowed(job.output_dir):
        return None
    _write_snapshot(job, report.run_id)
    ledger = RunLedger(Path(job.output_dir) / "ledger")
    ledger.save(report)
    return _report_path(job, report.run_id)


def _prepare_inventory(job: JobEnvelope) -> tuple[JobEnvelope, InventoryResult]:
    previous_hashes = None
    since_run_id = job.parameters.get("since_run_id")
    if since_run_id is not None:
        if not isinstance(since_run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", since_run_id):
            raise ValueError("since_run_id contains unsafe characters")
        previous_path = Path(job.output_dir) / "inventory" / f"{since_run_id}.json"
        try:
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("since_run_id inventory snapshot is unavailable") from exc
        if (
            not isinstance(previous, dict)
            or previous.get("schema") != "nemofold.inventory.v1"
            or not isinstance(previous.get("hashes_by_source_id"), dict)
        ):
            raise ValueError("since_run_id inventory snapshot is invalid")
        previous_hashes = previous["hashes_by_source_id"]
    inventory = scan_paths(job.input_roots, previous_hashes=previous_hashes)
    return replace(job, sources=inventory.records), inventory


def _write_inventory_snapshot(
    job: JobEnvelope,
    inventory: InventoryResult,
    *,
    run_id: str,
) -> ArtifactRecord:
    return write_text_artifact(
        Path(job.output_dir) / "inventory" / f"{run_id}.json",
        json.dumps(
            {
                "schema": "nemofold.inventory.v1",
                "run_id": run_id,
                "hashes_by_source_id": inventory.hashes_by_source_id(),
                "sources": [
                    {
                        "source_id": record.source_id,
                        "display_name": record.display_name,
                        "sha256": record.sha256,
                        "mime_type": record.mime_type,
                        "change_status": record.extraction_status,
                    }
                    for record in inventory.records
                ],
                "deleted_source_ids": list(inventory.deleted_source_ids),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "inventory-snapshot",
    )


def preview_job(
    job: JobEnvelope,
    config: ExecutionConfig,
    *,
    run_id: str,
) -> JobCommandResult:
    validate_run_id(run_id)
    gate = _gate(config)
    execution_decision = gate.evaluate(job)
    read_only_job = replace(
        job,
        action_mode=ActionMode.DRY_RUN,
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        model_id=None,
        model_budget_usd=0.0,
    )
    read_decision = gate.evaluate(read_only_job)
    if not read_decision.allowed:
        report = RunReport(
            run_id=run_id,
            idempotency_key=job_idempotency_key(job),
            workflow=job.workflow,
            status=RunStatus.BLOCKED,
            errors=read_decision.reasons,
            gate_decision=read_decision,
            metadata={"preview": True, "cloud_proof": False},
        )
        return JobCommandResult(report, _save_if_output_allowed(job, report, gate))

    prepared_read, inventory = _prepare_inventory(read_only_job)
    prepared = replace(job, sources=inventory.records)
    actions: tuple[str, ...] = ("inventory_scanned", "workflow_previewed")
    artifacts: tuple[ArtifactRecord, ...] = ()
    coverage: Coverage | None = None
    preview_metadata: dict[str, object] = {}
    try:
        validate_workflow_parameters(prepared)
        if prepared.workflow == "storage_policy":
            actions, artifacts, coverage, preview_metadata = _execute_storage_policy(
                prepared_read,
                inventory,
                run_id=run_id,
            )
        elif prepared.workflow == "smart_inbox":
            actions, artifacts, coverage, preview_metadata = _execute_smart_inbox(
                prepared_read,
                inventory,
                run_id=run_id,
            )
        elif prepared.workflow in {"evidence_analyst", "platform_proof"}:
            artifact, coverage, preview_metadata = _preview_context_receipts(
                prepared,
                inventory,
                run_id=run_id,
            )
            artifacts = (artifact,)
            actions += ("context_receipts_previewed",)
    except WorkflowBlocked as exc:
        actions = exc.actions
        artifacts = exc.artifacts
        coverage = exc.coverage
        preview_metadata = {**exc.metadata, "workflow_blockers": list(exc.errors)}
    except Exception as exc:
        report = RunReport(
            run_id=run_id,
            idempotency_key=job_idempotency_key(prepared),
            workflow=job.workflow,
            status=RunStatus.FAILED,
            errors=(f"preview_error:{type(exc).__name__}",),
            gate_decision=execution_decision,
            metadata={"preview": True, "cloud_proof": False},
        )
        return JobCommandResult(report, _save_if_output_allowed(prepared, report, gate))
    report = RunReport(
        run_id=run_id,
        idempotency_key=job_idempotency_key(prepared),
        workflow=job.workflow,
        status=RunStatus.PLANNED,
        actions=actions,
        gate_decision=execution_decision,
        coverage=coverage,
        artifacts=artifacts,
        metadata={
            "preview": True,
            "cloud_proof": False,
            "source_count": len(inventory.records),
            "new_source_ids": list(inventory.new_source_ids),
            "execution_gate_allowed": execution_decision.allowed,
            "execution_gate_reasons": list(execution_decision.reasons),
            **preview_metadata,
        },
    )
    return JobCommandResult(report, _save_if_output_allowed(prepared, report, gate))


def _read_text_sources(inventory: InventoryResult) -> dict[str, str]:
    texts: dict[str, str] = {}
    for source in inventory.records:
        if source.extraction_status in {"unreadable", "excluded_symlink"}:
            continue
        try:
            texts[source.source_id] = extract_document_text(
                source.path,
                mime_type=source.mime_type,
            )
        except (OSError, UnicodeError, ValueError):
            continue
    return texts


def _preview_context_receipts(
    job: JobEnvelope,
    inventory: InventoryResult,
    *,
    run_id: str,
) -> tuple[ArtifactRecord, Coverage, dict[str, object]]:
    texts = _read_text_sources(inventory)
    max_chunks = job.parameters.get("max_chunks", 8)
    if isinstance(max_chunks, bool) or not isinstance(max_chunks, int) or max_chunks < 1:
        raise ValueError("max_chunks must be a positive integer")
    index_status: dict[str, str] = {}
    index = DocumentIndex(Path(job.output_dir) / "index" / "nemofold.sqlite3")
    try:
        pruned_source_ids = index.prune_sources(frozenset(texts))
        for source in inventory.records:
            text = texts.get(source.source_id)
            if text is not None:
                index_status[source.source_id] = index.index_source(source, text)
        receipts = build_context_receipts(index, job.questions, hits_per_question=max_chunks)
    finally:
        index.close()
    coverage = compute_coverage(
        all_source_ids=(record.source_id for record in inventory.records),
        read_source_ids=texts,
        cited_source_ids=(),
    )
    if job.requires_external_model:
        sensitive_terms = job.parameters.get("pseudonymize_terms", [])
        if not isinstance(sensitive_terms, list) or any(
            not isinstance(item, str) for item in sensitive_terms
        ):
            raise ValueError("pseudonymize_terms must be a list of strings")
        sanitized = pseudonymize_questions_and_receipts(
            job.questions,
            receipts,
            sensitive_terms=sensitive_terms,
        )
        external_payload = job.to_external_payload()
        external_payload["questions"] = list(sanitized.questions)
        payload = {
            "schema": "nemofold.external-preview.v1",
            "transfer_performed": False,
            "recipient": "nebius",
            "payload": external_payload,
            "context_receipts": [receipt.to_payload() for receipt in sanitized.receipts],
            "privacy_receipt": {
                "schema": "nemofold.privacy-receipt.v1",
                "replacement_counts": sanitized.replacement_counts,
                "source_names_removed": True,
                "raw_mapping_stored": False,
                "transfer_performed": False,
            },
        }
        suffix = "external-preview"
        metadata = {
            "external_payload_prepared": True,
            "transfer_performed": False,
            "pseudonymization_counts": sanitized.replacement_counts,
            "index_status": index_status,
            "pruned_source_ids": pruned_source_ids,
        }
    else:
        payload = {
            "schema": "nemofold.context-preview.v1",
            "transfer_performed": False,
            "context_receipts": [receipt.to_payload() for receipt in receipts],
        }
        suffix = "context-preview"
        metadata = {
            "external_payload_prepared": False,
            "transfer_performed": False,
            "index_status": index_status,
            "pruned_source_ids": pruned_source_ids,
        }
    artifact = write_text_artifact(
        Path(job.output_dir) / f"{run_id}.{suffix}.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        suffix,
    )
    return artifact, coverage, metadata


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _execute_bundle(
    job: JobEnvelope,
    inventory: InventoryResult,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    texts = _read_text_sources(inventory)
    bundle_name = job.parameters.get("bundle_name", "document_bundle")
    if not isinstance(bundle_name, str):
        raise ValueError("bundle_name must be a string")
    result = create_text_bundle(
        inventory.records,
        texts,
        Path(job.output_dir) / "bundles",
        bundle_name=bundle_name,
    )
    records = (
        ArtifactRecord("bundle-text", str(result.bundle_path), result.bundle_sha256),
        ArtifactRecord("bundle-manifest", str(result.manifest_path), result.manifest_sha256),
        ArtifactRecord("bundle-zip", str(result.zip_path), _sha256_file(result.zip_path)),
    )
    read_ids = tuple(texts)
    coverage = compute_coverage(
        all_source_ids=(record.source_id for record in inventory.records),
        read_source_ids=read_ids,
        cited_source_ids=(),
    )
    return (
        ("inventory_scanned", "bundle_exported", "bundle_integrity_recorded"),
        records,
        coverage,
        {
            "included_sources": len(texts),
            "bundle_format": job.parameters.get("bundle_format", "text"),
            "order": job.parameters.get("order", "display_name"),
            "recursive": job.parameters.get("recursive", True),
            "include_manifest": job.parameters.get("include_manifest", True),
        },
    )


def _execute_digest(
    job: JobEnvelope,
    inventory: InventoryResult,
    *,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    texts = _read_text_sources(inventory)
    summary_length = job.parameters.get("summary_length", 3)
    if isinstance(summary_length, bool) or not isinstance(summary_length, int):
        raise ValueError("summary_length must be an integer")
    digest = build_digest(
        inventory.records,
        texts,
        max_sentences=summary_length,
        deleted_source_ids=inventory.deleted_source_ids,
    )
    artifact = write_text_artifact(
        Path(job.output_dir) / f"{run_id}.digest.md",
        digest.markdown,
        "folder-digest",
    )
    coverage = compute_coverage(
        all_source_ids=(record.source_id for record in inventory.records),
        read_source_ids=texts,
        cited_source_ids=(),
    )
    return (
        ("inventory_scanned", "folder_digest_built", "coverage_recorded"),
        (artifact,),
        coverage,
        {
            "new_source_ids": list(inventory.new_source_ids),
            "changed_source_ids": list(inventory.changed_source_ids),
            "unchanged_source_ids": list(inventory.unchanged_source_ids),
            "deleted_source_ids": list(inventory.deleted_source_ids),
            "gap_source_ids": list(digest.gap_source_ids),
            "digest_depth": job.parameters.get("digest_depth", "full"),
        },
    )


def _analysis_claim(
    question: str,
    hits: tuple[SearchHit, ...],
    *,
    conflict_scan: bool,
) -> Claim:
    if not hits:
        raise ValueError("analysis claim requires at least one search hit")
    primary = hits[0]
    quote = primary.text
    first_sentence = re.split(r"(?<=[.!?])\s+", quote.strip(), maxsplit=1)[0]
    fingerprints = {
        tuple(
            re.findall(
                r"(?i)\b(?:no|not|never|none|kein\w*|nicht|nie)\b|\b\d[\d.,/-]*\b",
                hit.text,
            )
        )
        for hit in hits
    }
    potential_conflict = conflict_scan and len(fingerprints - {()}) > 1
    evidence_hits = hits if potential_conflict else (primary,)
    locators: list[EvidenceLocator] = []
    seen_chunks: set[str] = set()
    for hit in evidence_hits:
        if hit.chunk_id in seen_chunks:
            continue
        section = f"lines {hit.line_start}-{hit.line_end}"
        if (
            hit.page_start is not None
            and hit.page_end is not None
            and hit.page_end != hit.page_start
        ):
            section += f", through page {hit.page_end}"
        locators.append(
            EvidenceLocator(
                source_id=hit.source_id,
                quote=hit.text,
                page=hit.page_start,
                section=section,
            )
        )
        seen_chunks.add(hit.chunk_id)
        if len(locators) == 3:
            break
    return Claim(
        statement=f"For '{question}', the strongest local passage states: {first_sentence}",
        evidence=tuple(locators),
        uncertainty=0.5,
        conflict_status="potential_conflict" if potential_conflict else "none",
    )


def _execute_evidence(
    job: JobEnvelope,
    inventory: InventoryResult,
    *,
    run_id: str,
    platform_proof: bool = False,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    texts = _read_text_sources(inventory)
    max_chunks = job.parameters.get("max_chunks", 8)
    if isinstance(max_chunks, bool) or not isinstance(max_chunks, int) or max_chunks < 1:
        raise ValueError("max_chunks must be a positive integer")
    conflict_scan = job.parameters.get("conflict_scan", True)
    if not isinstance(conflict_scan, bool):
        raise ValueError("conflict_scan must be a boolean")
    index_status: dict[str, str] = {}
    index = DocumentIndex(Path(job.output_dir) / "index" / "nemofold.sqlite3")
    try:
        pruned_source_ids = index.prune_sources(frozenset(texts))
        for source in inventory.records:
            text = texts.get(source.source_id)
            if text is not None:
                index_status[source.source_id] = index.index_source(source, text)
        receipts = build_context_receipts(index, job.questions, hits_per_question=max_chunks)
    finally:
        index.close()

    answers: list[dict[str, Any]] = []
    claims: list[Claim] = []
    unanswered: list[str] = []
    for receipt in receipts:
        if not receipt.hits:
            unanswered.append(receipt.question)
            answers.append({"question": receipt.question, "claim": None, "verified": False})
            continue
        claim = _analysis_claim(
            receipt.question,
            receipt.hits,
            conflict_scan=conflict_scan,
        )
        validation = validate_claim(claim, texts)
        answers.append(
            {
                "question": receipt.question,
                "claim": to_primitive(claim),
                "verified": validation.verified,
            }
        )
        if validation.verified:
            claims.append(claim)
        else:
            unanswered.append(receipt.question)

    cited_ids = {locator.source_id for claim in claims for locator in claim.evidence}
    coverage = compute_coverage(
        all_source_ids=(record.source_id for record in inventory.records),
        read_source_ids=texts,
        cited_source_ids=cited_ids,
    )
    source_labels = {record.source_id: record.display_name for record in inventory.records}
    receipt_record = write_text_artifact(
        Path(job.output_dir) / f"{run_id}.context-receipts.json",
        json.dumps([receipt.to_payload() for receipt in receipts], indent=2, sort_keys=True) + "\n",
        "context-receipts",
    )
    analysis_payload = {
        "schema": "nemofold.analysis.v1",
        "title": job.parameters.get("title", "NemoFold evidence analysis"),
        "answers": answers,
        "coverage": to_primitive(coverage),
        "source_labels": source_labels,
        "unanswered_questions": unanswered,
        "analysis_adapter": "local_extractive_v1",
        "potential_conflict_questions": [
            answer["question"]
            for answer in answers
            if isinstance(answer.get("claim"), dict)
            and answer["claim"].get("conflict_status") == "potential_conflict"
        ],
    }
    analysis_record = write_text_artifact(
        Path(job.output_dir) / f"{run_id}.analysis.json",
        json.dumps(analysis_payload, indent=2, sort_keys=True) + "\n",
        "analysis-json",
    )
    formats = job.parameters.get("formats", ["md", "txt"])
    if not isinstance(formats, list) or any(not isinstance(item, str) for item in formats):
        raise ValueError("formats must be a list of strings")
    report_records = render_report_formats(
        ReportDocument(
            title=str(analysis_payload["title"]),
            claims=tuple(claims),
            coverage=coverage,
            source_labels=tuple(source_labels.items()),
        ),
        job.output_dir,
        basename=run_id,
        formats=tuple(formats),
    )
    actions: tuple[str, ...] = (
        "inventory_scanned",
        "local_index_built",
        "context_receipts_built",
        "claims_validated",
        "reports_exported",
    )
    metadata: dict[str, object] = {
        "analysis_adapter": "local_extractive_v1",
        "answered_questions": len(claims),
        "unanswered_questions": unanswered,
        "potential_conflicts": sum(
            claim.conflict_status == "potential_conflict" for claim in claims
        ),
        "analysis_mode": job.parameters.get("analysis_mode", "local_extractive"),
        "citation_granularity": job.parameters.get("citation_granularity", "line_or_page"),
        "index_status": index_status,
        "pruned_source_ids": pruned_source_ids,
    }
    if platform_proof:
        actions += ("offline_platform_proof",)
        metadata.update(
            {
                "evidence_level": "offline",
                "requested_runtime": job.parameters.get("runtime", "offline"),
                "network_gate": job.parameters.get("network_gate", "closed"),
                "cloud_proof": False,
            }
        )
    return (
        actions,
        (analysis_record, receipt_record) + report_records,
        coverage,
        metadata,
    )


def _filename_issue_date(name: str) -> date | None:
    match = re.search(r"(?<!\d)(20\d{2})[-_](\d{2})[-_](\d{2})(?!\d)", name)
    if not match:
        return None
    try:
        return date(*(int(item) for item in match.groups()))
    except ValueError:
        return None


def _filename_version(name: str) -> tuple[int, ...] | None:
    match = re.search(r"(?i)(?:^|[_-])v(\d+(?:[._-]\d+)*)", name)
    return tuple(int(item) for item in re.split(r"[._-]", match.group(1))) if match else None


def _optional_iso_date(value: object, *, field_name: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO date string")
    return date.fromisoformat(value)


def _optional_version(value: object) -> tuple[int, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        parts = value.removeprefix("v").removeprefix("V").split(".")
    elif isinstance(value, list):
        parts = value
    else:
        raise ValueError("version_number must be a dotted string or integer list")
    if not parts or any(isinstance(item, bool) or not str(item).isdigit() for item in parts):
        raise ValueError("version_number contains an invalid component")
    return tuple(int(item) for item in parts)


def _version_overrides(job: JobEnvelope, source_id: str, display_name: str) -> dict[str, Any]:
    value = job.parameters.get("validity_fields", {})
    if not isinstance(value, dict):
        raise ValueError("validity_fields must be an object")
    selected = value.get(source_id, value.get(display_name, {}))
    if not isinstance(selected, dict):
        raise ValueError("each validity_fields entry must be an object")
    allowed = {"issue_date", "valid_from", "valid_until", "version_number"}
    unknown = set(selected) - allowed
    if unknown:
        raise ValueError(f"unknown validity field: {sorted(unknown)[0]}")
    return selected


def _version_family(job: JobEnvelope, source_id: str, display_name: str) -> str:
    hint = job.parameters.get("family_hint")
    if hint is None:
        return infer_family_key(display_name)
    if isinstance(hint, str) and hint.strip():
        return hint.strip()
    if isinstance(hint, dict):
        family = hint.get(source_id, hint.get(display_name))
        if isinstance(family, str) and family.strip():
            return family.strip()
    raise ValueError("family_hint must be a non-empty string or source mapping")


def _execute_versions(
    job: JobEnvelope,
    inventory: InventoryResult,
    *,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    texts = _read_text_sources(inventory)
    as_of_value = job.parameters.get("as_of", date.today().isoformat())
    if not isinstance(as_of_value, str):
        raise ValueError("as_of must be an ISO date string")
    as_of = date.fromisoformat(as_of_value)
    fallback_value = job.parameters.get("fallback_to_file_time", True)
    if not isinstance(fallback_value, bool):
        raise ValueError("fallback_to_file_time must be a boolean")
    families: dict[str, list[VersionCandidate]] = {}
    for record in inventory.records:
        if record.source_id not in texts:
            continue
        overrides = _version_overrides(job, record.source_id, record.display_name)
        candidate = VersionCandidate(
            source_id=record.source_id,
            display_name=record.display_name,
            issue_date=_optional_iso_date(overrides.get("issue_date"), field_name="issue_date")
            or _filename_issue_date(record.display_name),
            valid_from=_optional_iso_date(overrides.get("valid_from"), field_name="valid_from"),
            valid_until=_optional_iso_date(overrides.get("valid_until"), field_name="valid_until"),
            version_number=_optional_version(overrides.get("version_number"))
            or _filename_version(record.display_name),
            file_time=datetime.fromtimestamp(Path(record.path).stat().st_mtime, tz=UTC),
        )
        family = _version_family(job, record.source_id, record.display_name)
        families.setdefault(family, []).append(candidate)
    if not families:
        raise ValueError("version_resolver found no readable candidates")

    family_payloads: list[dict[str, object]] = []
    resolutions = []
    for family, candidates in sorted(families.items()):
        resolution = resolve_current(
            candidates,
            as_of=as_of,
            fallback_to_file_time=fallback_value,
        )
        resolutions.append(resolution)
        comparison_source = next(
            (
                item
                for item in resolution.ordered_source_ids
                if item != resolution.selected.source_id
            ),
            None,
        )
        comparison = compare_versions(
            texts[comparison_source] if comparison_source is not None else "",
            texts[resolution.selected.source_id],
        )
        family_payloads.append(
            {
                "family": family,
                "basis": resolution.basis,
                "selected": to_primitive(resolution.selected),
                "ordered_source_ids": list(resolution.ordered_source_ids),
                "comparison_source_id": comparison_source,
                "comparison": to_primitive(comparison),
            }
        )
    first = resolutions[0]
    payload = {
        "schema": "nemofold.version-resolution.v1",
        "as_of": as_of.isoformat(),
        "families": family_payloads,
        "basis": first.basis if len(resolutions) == 1 else "per_family",
        "selected": to_primitive(first.selected) if len(resolutions) == 1 else None,
        "ordered_source_ids": (list(first.ordered_source_ids) if len(resolutions) == 1 else []),
        "comparison": family_payloads[0]["comparison"] if len(resolutions) == 1 else None,
    }
    artifact = write_text_artifact(
        Path(job.output_dir) / f"{run_id}.versions.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        "version-resolution",
    )
    coverage = compute_coverage(
        all_source_ids=(record.source_id for record in inventory.records),
        read_source_ids=texts,
        cited_source_ids=(),
    )
    return (
        ("inventory_scanned", "version_candidates_ranked", "version_diff_built"),
        (artifact,),
        coverage,
        {
            "version_basis": first.basis if len(resolutions) == 1 else "per_family",
            "selected_source_id": first.selected.source_id if len(resolutions) == 1 else None,
            "selected_display_name": (
                first.selected.display_name if len(resolutions) == 1 else None
            ),
            "selected_source_ids": [item.selected.source_id for item in resolutions],
            "family_count": len(resolutions),
        },
    )


def _claim_from_payload(value: Any) -> Claim:
    if not isinstance(value, dict) or not isinstance(value.get("statement"), str):
        raise ValueError("analysis claim is invalid")
    evidence_value = value.get("evidence", [])
    if not isinstance(evidence_value, list):
        raise ValueError("analysis claim evidence is invalid")
    evidence = tuple(
        EvidenceLocator(
            source_id=item["source_id"],
            quote=item["quote"],
            page=item.get("page"),
            section=item.get("section"),
        )
        for item in evidence_value
        if isinstance(item, dict)
        and isinstance(item.get("source_id"), str)
        and isinstance(item.get("quote"), str)
    )
    if len(evidence) != len(evidence_value):
        raise ValueError("analysis evidence locator is invalid")
    return Claim(
        statement=value["statement"],
        evidence=evidence,
        uncertainty=float(value.get("uncertainty", 0.0)),
        conflict_status=str(value.get("conflict_status", "none")),
    )


def _execute_report_studio(
    job: JobEnvelope,
    inventory: InventoryResult,
    *,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    json_sources = [record for record in inventory.records if Path(record.path).suffix == ".json"]
    if len(json_sources) != 1:
        raise ValueError("report_studio requires exactly one analysis JSON input")
    payload = json.loads(Path(json_sources[0].path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "nemofold.analysis.v1":
        raise ValueError("analysis schema is invalid")
    answers = payload.get("answers")
    if not isinstance(answers, list):
        raise ValueError("analysis answers are invalid")
    claims = tuple(
        _claim_from_payload(answer["claim"])
        for answer in answers
        if isinstance(answer, dict)
        and answer.get("claim") is not None
        and answer.get("verified") is True
    )
    if any(
        isinstance(answer, dict)
        and answer.get("claim") is not None
        and answer.get("verified") is not True
        for answer in answers
    ):
        raise ValueError("report_studio refuses unverified claims")
    coverage_value = payload.get("coverage")
    if not isinstance(coverage_value, dict):
        raise ValueError("analysis coverage is invalid")
    coverage = Coverage(
        total_sources=int(coverage_value["total_sources"]),
        read_sources=int(coverage_value["read_sources"]),
        cited_sources=int(coverage_value["cited_sources"]),
        unread_source_ids=tuple(coverage_value.get("unread_source_ids", ())),
        uncited_read_source_ids=tuple(coverage_value.get("uncited_read_source_ids", ())),
    )
    source_labels_value = payload.get("source_labels", {})
    if not isinstance(source_labels_value, dict):
        raise ValueError("analysis source labels are invalid")
    cited_source_ids = {locator.source_id for claim in claims for locator in claim.evidence}
    if not cited_source_ids.issubset(source_labels_value):
        raise ValueError("analysis claim references an unknown source label")
    if coverage.cited_sources != len(cited_source_ids):
        raise ValueError("analysis coverage does not match cited source IDs")
    formats = job.parameters.get("formats", ["md", "txt", "pdf", "docx", "odt"])
    if not isinstance(formats, list) or any(not isinstance(item, str) for item in formats):
        raise ValueError("formats must be a list of strings")
    records = render_report_formats(
        ReportDocument(
            title=str(payload.get("title", "NemoFold report")),
            claims=claims,
            coverage=coverage,
            source_labels=tuple(
                (str(source_id), str(label)) for source_id, label in source_labels_value.items()
            ),
        ),
        job.output_dir,
        basename=run_id,
        formats=tuple(formats),
    )
    return (
        ("analysis_contract_loaded", "verified_claims_selected", "reports_exported"),
        records,
        coverage,
        {
            "rendered_formats": list(formats),
            "claim_count": len(claims),
            "template": job.parameters.get("template", "default"),
            "language": job.parameters.get("language", "en"),
            "include_coverage": job.parameters.get("include_coverage", True),
        },
    )


def _action_policy_set(job: JobEnvelope, *, default_original: str) -> PolicySet:
    extensions = job.parameters.get("allowed_extensions", job.parameters.get("allowed_types", []))
    if not isinstance(extensions, list) or any(not isinstance(item, str) for item in extensions):
        raise ValueError("allowed_extensions must be a list of strings")
    naming = job.parameters.get("naming_template", "{stem}{suffix}")
    retention = job.parameters.get("retention_action", job.parameters.get("retention_rule", "keep"))
    original = job.parameters.get("original_policy", default_original)
    conversion = job.parameters.get("conversion_target")
    if not all(isinstance(item, str) for item in (naming, retention, original)):
        raise ValueError("storage policy values must be strings")
    if conversion is not None and not isinstance(conversion, str):
        raise ValueError("conversion_target must be a string or null")
    rules = tuple(
        PolicyRule(
            scope=root if root.is_dir() else root.parent,
            naming_template=naming,
            allowed_extensions=tuple(extensions),
            retention_action=retention,
            original_policy=original,
            conversion_target=conversion,
        )
        for root in (Path(value) for value in job.input_roots)
    )
    return PolicySet(rules=rules)


def _action_coverage(inventory: InventoryResult) -> Coverage:
    source_ids = tuple(record.source_id for record in inventory.records)
    return compute_coverage(
        all_source_ids=source_ids,
        read_source_ids=(),
        cited_source_ids=(),
    )


def _finalize_action_plans(
    job: JobEnvelope,
    inventory: InventoryResult,
    plans: tuple[StoragePlan, ...],
    *,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    plan_record = write_text_artifact(
        Path(job.output_dir) / f"{run_id}.action-plan.json",
        json.dumps(
            {
                "schema": "nemofold.action-plan.v1",
                "run_id": run_id,
                "workflow": job.workflow,
                "plans": [to_primitive(plan) for plan in plans],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "action-plan",
    )
    coverage = _action_coverage(inventory)
    action_metadata: dict[str, object] = {"planned_actions": len(plans)}
    if job.workflow == "smart_inbox":
        action_metadata.update(
            {
                "classification_policy": job.parameters.get(
                    "classification_policy", "suffix_routes"
                ),
                "confidence_threshold": job.parameters.get("confidence_threshold", 1.0),
            }
        )
    else:
        action_metadata.update(
            {
                "conversion_target": job.parameters.get("conversion_target"),
                "retention_rule": job.parameters.get(
                    "retention_action", job.parameters.get("retention_rule", "keep")
                ),
                "original_policy": job.parameters.get("original_policy", "move"),
            }
        )
    blocked_reasons = tuple(
        dict.fromkeys(reason for plan in plans if not plan.allowed for reason in plan.reasons)
    )
    if blocked_reasons:
        raise WorkflowBlocked(
            blocked_reasons,
            actions=("action_plan_written", "action_batch_blocked"),
            artifacts=(plan_record,),
            coverage=coverage,
            metadata={**action_metadata, "applied_actions": 0},
        )
    if job.action_mode is ActionMode.DRY_RUN:
        return (
            ("action_plan_written", "dry_run_completed"),
            (plan_record,),
            coverage,
            {**action_metadata, "applied_actions": 0},
        )

    journal = ActionJournal(
        Path(job.output_dir) / "actions" / f"{run_id}.json",
        run_id=run_id,
    )
    if not journal.path.exists():
        journal.plan(plans)
    receipts = journal.execute(plans)
    receipt_record = write_text_artifact(
        Path(job.output_dir) / f"{run_id}.undo-receipts.json",
        json.dumps(
            {
                "schema": "nemofold.undo-receipts.v1",
                "run_id": run_id,
                "receipts": [to_primitive(receipt) for receipt in receipts],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "undo-receipts",
    )
    return (
        (
            "action_plan_written",
            "action_journal_written",
            "moves_executed",
            "undo_receipts_written",
        ),
        (plan_record, receipt_record),
        coverage,
        {**action_metadata, "applied_actions": len(receipts)},
    )


def _load_action_plans(job: JobEnvelope, *, run_id: str) -> tuple[StoragePlan, ...] | None:
    path = Path(job.output_dir) / f"{run_id}.action-plan.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "nemofold.action-plan.v1"
        or payload.get("run_id") != run_id
        or payload.get("workflow") != job.workflow
        or not isinstance(payload.get("plans"), list)
    ):
        raise RuntimeError("stored action plan is invalid")
    try:
        return tuple(
            StoragePlan(
                source=item["source"],
                target=item["target"],
                allowed=item["allowed"],
                reasons=tuple(item.get("reasons", ())),
                retention_action=item["retention_action"],
                original_policy=item["original_policy"],
                operation=item.get("operation", "move"),
                conversion_target=item.get("conversion_target"),
            )
            for item in payload["plans"]
        )
    except (KeyError, TypeError) as exc:
        raise RuntimeError("stored action plan contract is invalid") from exc


def _execute_storage_policy(
    job: JobEnvelope,
    inventory: InventoryResult,
    *,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    existing = _load_action_plans(job, run_id=run_id)
    if len(job.target_roots) != 1:
        raise ValueError("storage_policy requires exactly one target root")
    target = Path(job.target_roots[0])
    if not target.is_dir():
        raise FileNotFoundError(target)
    policies = _action_policy_set(job, default_original="move")
    plans = tuple(
        preview_storage(record.path, target, policies.resolve(record.path))
        for record in inventory.records
    )
    if existing is not None and job.action_mode is ActionMode.APPLY:
        if existing != plans:
            raise RuntimeError("stored action plan does not match the current approved plan")
        return _finalize_action_plans(job, inventory, existing, run_id=run_id)
    return _finalize_action_plans(job, inventory, plans, run_id=run_id)


def _execute_smart_inbox(
    job: JobEnvelope,
    inventory: InventoryResult,
    *,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    existing = _load_action_plans(job, run_id=run_id)
    routes_value = job.parameters.get("routes")
    if not isinstance(routes_value, list) or not routes_value:
        raise ValueError("smart_inbox requires at least one route")
    routes: list[RoutingRule] = []
    for value in routes_value:
        if not isinstance(value, dict):
            raise ValueError("smart_inbox route must be an object")
        suffixes = value.get("suffixes")
        target_index = value.get("target_root")
        if (
            not isinstance(suffixes, list)
            or any(not isinstance(item, str) for item in suffixes)
            or isinstance(target_index, bool)
            or not isinstance(target_index, int)
            or not 0 <= target_index < len(job.target_roots)
        ):
            raise ValueError("smart_inbox route is invalid")
        target = Path(job.target_roots[target_index])
        if not target.is_dir():
            raise FileNotFoundError(target)
        routes.append(RoutingRule(suffixes=tuple(suffixes), target_dir=target))
    plans = plan_inbox(
        (record.path for record in inventory.records),
        rules=tuple(routes),
        policies=_action_policy_set(job, default_original="move"),
    )
    if existing is not None and job.action_mode is ActionMode.APPLY:
        if existing != plans:
            raise RuntimeError("stored action plan does not match the current approved plan")
        return _finalize_action_plans(job, inventory, existing, run_id=run_id)
    return _finalize_action_plans(job, inventory, plans, run_id=run_id)


def _dispatch_workflow(
    job: JobEnvelope,
    inventory: InventoryResult,
    *,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    validate_workflow_parameters(job)
    if job.workflow == "bundle_export":
        return _execute_bundle(job, inventory)
    if job.workflow == "folder_digest":
        return _execute_digest(job, inventory, run_id=run_id)
    if job.workflow == "evidence_analyst":
        return _execute_evidence(job, inventory, run_id=run_id)
    if job.workflow == "version_resolver":
        return _execute_versions(job, inventory, run_id=run_id)
    if job.workflow == "report_studio":
        return _execute_report_studio(job, inventory, run_id=run_id)
    if job.workflow == "platform_proof":
        return _execute_evidence(job, inventory, run_id=run_id, platform_proof=True)
    if job.workflow == "storage_policy":
        return _execute_storage_policy(job, inventory, run_id=run_id)
    if job.workflow == "smart_inbox":
        return _execute_smart_inbox(job, inventory, run_id=run_id)
    raise NotImplementedError(f"workflow_not_implemented:{job.workflow}")


def _complete_running_job(
    job: JobEnvelope,
    inventory: InventoryResult,
    running: RunReport,
    ledger: RunLedger,
) -> JobCommandResult:
    run_id = running.run_id
    inventory_record = _write_inventory_snapshot(job, inventory, run_id=run_id)
    try:
        actions, artifacts, coverage, metadata = _dispatch_workflow(
            job,
            inventory,
            run_id=run_id,
        )
    except WorkflowBlocked as exc:
        blocked = replace(
            running,
            status=RunStatus.BLOCKED,
            actions=exc.actions,
            errors=exc.errors,
            artifacts=(inventory_record,) + exc.artifacts,
            coverage=exc.coverage,
            metadata={**running.metadata, **exc.metadata},
        )
        ledger.update(blocked)
        return JobCommandResult(blocked, _report_path(job, run_id))
    except Exception as exc:
        reason = (
            str(exc)
            if isinstance(exc, NotImplementedError)
            else f"workflow_error:{type(exc).__name__}"
        )
        failed = replace(
            running,
            status=RunStatus.FAILED,
            errors=(reason,),
            artifacts=(inventory_record,),
        )
        ledger.update(failed)
        return JobCommandResult(failed, _report_path(job, run_id))
    final = replace(
        running,
        status=RunStatus.EXECUTED,
        actions=actions,
        errors=(),
        artifacts=(inventory_record,) + artifacts,
        coverage=coverage,
        metadata={**running.metadata, **metadata},
    )
    ledger.update(final)
    return JobCommandResult(final, _report_path(job, run_id))


def run_job(
    job: JobEnvelope,
    config: ExecutionConfig,
    *,
    run_id: str,
) -> JobCommandResult:
    validate_run_id(run_id)
    gate = _gate(config)
    initial_decision = gate.evaluate(job)
    if not initial_decision.allowed:
        report = RunReport(
            run_id=run_id,
            idempotency_key=job_idempotency_key(job),
            workflow=job.workflow,
            status=RunStatus.BLOCKED,
            errors=initial_decision.reasons,
            gate_decision=initial_decision,
            metadata={"cloud_proof": False},
        )
        return JobCommandResult(report, _save_if_output_allowed(job, report, gate))

    early_ledger = RunLedger(Path(job.output_dir) / "ledger")
    try:
        early_existing = early_ledger.load(run_id)
    except FileNotFoundError:
        early_existing = None
    if early_existing is not None and early_existing.status is RunStatus.EXECUTED:
        snapshot = load_job_snapshot(_snapshot_path(job, run_id))
        if job_idempotency_key(replace(snapshot, sources=())) != job_idempotency_key(job):
            raise ValueError("run_id already belongs to a different job identity")
        return JobCommandResult(early_existing, _report_path(job, run_id))

    prepared, inventory = _prepare_inventory(job)
    decision = gate.evaluate(prepared)
    identity = job_idempotency_key(prepared)
    ledger = RunLedger(Path(prepared.output_dir) / "ledger")
    try:
        existing = ledger.load(run_id)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if existing.workflow != prepared.workflow or existing.idempotency_key != identity:
            raise ValueError("run_id already belongs to a different job identity")
        if existing.status is RunStatus.EXECUTED:
            return JobCommandResult(existing, _report_path(prepared, run_id))
        if existing.status is not RunStatus.PLANNED:
            raise ValueError("blocked or failed runs must use the resume command")
    if prepared.requires_external_model:
        report = RunReport(
            run_id=run_id,
            idempotency_key=identity,
            workflow=prepared.workflow,
            status=RunStatus.BLOCKED,
            errors=("external_runtime_unavailable",),
            gate_decision=decision,
            metadata={"cloud_proof": False, "source_count": len(inventory.records)},
        )
        if existing is None:
            ledger.save(report)
        else:
            ledger.update(report)
        return JobCommandResult(report, _report_path(prepared, run_id))

    _write_snapshot(prepared, run_id)
    if existing is None:
        initial = RunReport(
            run_id=run_id,
            idempotency_key=identity,
            workflow=prepared.workflow,
            status=RunStatus.PLANNED,
            gate_decision=decision,
            metadata={"cloud_proof": False, "source_count": len(inventory.records)},
        )
        ledger.save(initial)
        running = ledger.transition(run_id, RunStatus.RUNNING)
    else:
        running = replace(
            existing,
            status=RunStatus.RUNNING,
            actions=(),
            errors=(),
            gate_decision=decision,
            artifacts=(),
            coverage=None,
            metadata={
                **existing.metadata,
                "preview": False,
                "source_count": len(inventory.records),
            },
        )
        ledger.update(running)
    return _complete_running_job(prepared, inventory, running, ledger)


def resume_job(
    job: JobEnvelope,
    config: ExecutionConfig,
    *,
    run_id: str,
) -> JobCommandResult:
    validate_run_id(run_id)
    ledger = RunLedger(Path(job.output_dir) / "ledger")
    current = ledger.load(run_id)
    if current.workflow != job.workflow or current.idempotency_key != job_idempotency_key(job):
        raise ValueError("resume job identity does not match the existing run")
    if current.status is RunStatus.EXECUTED:
        return JobCommandResult(current, _report_path(job, run_id))

    gate = _gate(config)
    decision = gate.evaluate(job)
    if not decision.allowed:
        blocked = replace(
            current,
            status=RunStatus.BLOCKED,
            errors=decision.reasons,
            gate_decision=decision,
        )
        ledger.update(blocked)
        return JobCommandResult(blocked, _report_path(job, run_id))
    if job.requires_external_model:
        blocked = replace(
            current,
            status=RunStatus.BLOCKED,
            errors=("external_runtime_unavailable",),
            gate_decision=decision,
            metadata={**current.metadata, "cloud_proof": False},
        )
        ledger.update(blocked)
        return JobCommandResult(blocked, _report_path(job, run_id))

    if job.sources:
        inventory = InventoryResult(
            root=job.input_roots[0] if len(job.input_roots) == 1 else "<multiple>",
            records=job.sources,
            new_source_ids=tuple(source.source_id for source in job.sources),
            changed_source_ids=(),
            unchanged_source_ids=(),
            deleted_source_ids=(),
            roots=job.input_roots,
        )
        prepared = job
    else:
        prepared, inventory = _prepare_inventory(job)
        if job_idempotency_key(prepared) != current.idempotency_key:
            raise ValueError("resume source inventory no longer matches the existing run")
    running = replace(
        current,
        status=RunStatus.RUNNING,
        errors=(),
        gate_decision=decision,
        metadata={**current.metadata, "resume_attempted": True},
    )
    ledger.update(running)
    return _complete_running_job(prepared, inventory, running, ledger)


def undo_run(
    output_dir: str | Path,
    config: ExecutionConfig,
    *,
    run_id: str,
) -> JobCommandResult:
    validate_run_id(run_id)
    output = Path(output_dir).resolve()
    gate = _gate(config)
    if not gate.path_allowed(str(output)):
        raise PermissionError("output_path_not_allowed")
    original = RunLedger(output / "ledger").load(run_id)
    if original.status is not RunStatus.EXECUTED:
        raise RuntimeError("only an executed run can be undone")
    journal = ActionJournal(output / "actions" / f"{run_id}.json", run_id=run_id)
    if not journal.path.is_file():
        raise FileNotFoundError("run has no action journal")
    if any(not gate.path_allowed(str(path)) for path in journal.controlled_paths()):
        raise PermissionError("undo_path_not_allowed")
    if not config.apply_actions_allowed:
        raise PermissionError("undo_requires_immediate_approval")

    undo_run_id = f"undo_{run_id}"
    ledger = RunLedger(output / "ledger")
    try:
        existing = ledger.load(undo_run_id)
    except FileNotFoundError:
        existing = None
    if existing is not None and existing.status is RunStatus.EXECUTED:
        journal.undo()
        return JobCommandResult(existing, output / "ledger" / f"{undo_run_id}.json")

    identity = "job_" + hashlib.sha256(f"undo:{run_id}".encode()).hexdigest()
    initial = RunReport(
        run_id=undo_run_id,
        idempotency_key=identity,
        workflow="undo",
        status=RunStatus.PLANNED,
        gate_decision=GateDecision(allowed=True),
        metadata={"cloud_proof": False, "original_run_id": run_id},
    )
    ledger.save(initial)
    running = ledger.transition(undo_run_id, RunStatus.RUNNING)
    try:
        receipts = journal.undo()
        artifact = write_text_artifact(
            output / f"{undo_run_id}.json",
            json.dumps(
                {
                    "schema": "nemofold.undo-result.v1",
                    "original_run_id": run_id,
                    "receipts": [to_primitive(receipt) for receipt in receipts],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "undo-result",
        )
    except Exception as exc:
        failed = replace(
            running,
            status=RunStatus.FAILED,
            errors=(f"undo_error:{type(exc).__name__}",),
        )
        ledger.update(failed)
        return JobCommandResult(failed, output / "ledger" / f"{undo_run_id}.json")
    final = replace(
        running,
        status=RunStatus.EXECUTED,
        actions=("undo_preflight_completed", "moves_undone", "undo_verified"),
        artifacts=(artifact,),
        metadata={
            **running.metadata,
            "undone_actions": len(receipts),
        },
    )
    ledger.update(final)
    return JobCommandResult(final, output / "ledger" / f"{undo_run_id}.json")
