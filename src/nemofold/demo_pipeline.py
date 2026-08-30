from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from .artifacts import write_text_artifact
from .bundle_export import create_text_bundle
from .contracts import (
    ActionMode,
    ArtifactRecord,
    Claim,
    EvidenceLocator,
    JobEnvelope,
    PrivacyMode,
    RunReport,
)
from .demo import DeterministicDemoReasoner
from .document_index import DocumentIndex
from .evidence_analyst import build_context_receipts
from .folder_digest import build_digest
from .inventory import scan_root
from .ledger import RunLedger
from .policy import PolicyConfig, PolicyGate
from .report_studio import ReportDocument, render_report_formats
from .runtime import LocalAgentRuntime
from .smart_inbox import RoutingRule, apply_move, plan_inbox, undo_move
from .storage_policy import PolicyRule, PolicySet
from .version_resolver import VersionCandidate, resolve_current


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_texts(records) -> dict[str, str]:
    return {
        source.source_id: Path(source.path).read_text(encoding="utf-8")
        for source in records
        if source.mime_type in {"text/plain", "text/markdown"}
        and source.extraction_status != "unreadable"
    }


def _source_by_name(records, name: str):
    return next((record for record in records if record.display_name == name), None)


def run_full_offline_demo(
    input_root: str | Path,
    output_root: str | Path,
    *,
    run_id: str,
) -> RunReport:
    source_fixture = Path(input_root).resolve()
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    workspace = output / "workspaces" / run_id
    shutil.copytree(source_fixture, workspace)

    inbox = workspace / "inbox"
    documents = workspace / "documents"
    inbox.mkdir()
    documents.mkdir()
    incoming = inbox / "incoming_note.txt"
    incoming.write_text("Synthetic inbox note for reversible routing.\n", encoding="utf-8")

    policy_set = PolicySet(
        rules=(PolicyRule(scope=workspace, allowed_extensions=(".txt",)),)
    )
    move_plan = plan_inbox(
        (incoming,),
        rules=(RoutingRule(suffixes=(".txt",), target_dir=documents),),
        policies=policy_set,
    )[0]
    undo_receipt = undo_move(apply_move(move_plan, approved=True), approved=True)

    inventory = scan_root(workspace)
    source_texts = _source_texts(inventory.records)
    bundle = create_text_bundle(
        inventory.records,
        source_texts,
        output / "bundles",
        bundle_name=run_id,
    )
    digest = build_digest(inventory.records, source_texts)
    digest_record = write_text_artifact(
        output / f"{run_id}.digest.md", digest.markdown, "folder-digest"
    )

    index = DocumentIndex(output / "index" / f"{run_id}.sqlite3")
    try:
        for source in inventory.records:
            text = source_texts.get(source.source_id)
            if text is not None:
                index.index_source(source, text)
        receipts = build_context_receipts(
            index,
            ("When does coverage begin?", "When does the policy expire?"),
            hits_per_question=3,
        )
        receipt_json = json.dumps(
            [receipt.to_payload() for receipt in receipts],
            indent=2,
            sort_keys=True,
        )
    finally:
        index.close()
    receipt_record = write_text_artifact(
        output / f"{run_id}.context-receipts.json",
        receipt_json + "\n",
        "context-receipts",
    )

    job = JobEnvelope(
        workflow="platform_proof",
        input_roots=(str(workspace),),
        output_dir=str(output),
        questions=("When does the current synthetic policy begin?",),
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        action_mode=ActionMode.DRY_RUN,
        sources=inventory.records,
    )
    ledger = RunLedger(output / "ledger")
    runtime = LocalAgentRuntime(
        gate=PolicyGate(
            PolicyConfig(
                allowed_roots=(str(workspace), str(output)),
                external_models_allowed=False,
            )
        ),
        ledger=ledger,
    )
    runtime_result = runtime.execute(
        job,
        DeterministicDemoReasoner(),
        source_texts,
        run_id=run_id,
    )

    current = _source_by_name(inventory.records, "current_policy.txt")
    old = _source_by_name(inventory.records, "old_policy.txt")
    if current is None or old is None:
        raise ValueError("demo fixture requires current_policy.txt and old_policy.txt")
    resolution = resolve_current(
        (
            VersionCandidate(
                source_id=current.source_id,
                display_name=current.display_name,
                issue_date=date(2026, 3, 1),
                valid_from=date(2026, 4, 1),
                valid_until=date(2026, 12, 31),
                file_time=datetime(2026, 3, 1, tzinfo=UTC),
            ),
            VersionCandidate(
                source_id=old.source_id,
                display_name=old.display_name,
                issue_date=date(2025, 3, 1),
                valid_from=date(2025, 4, 1),
                valid_until=date(2025, 12, 31),
                file_time=datetime(2026, 8, 1, tzinfo=UTC),
            ),
        ),
        as_of=date(2026, 8, 30),
    )
    version_quote = next(
        line.strip()
        for line in source_texts[current.source_id].splitlines()
        if "31 December 2026" in line
    )
    version_claim = Claim(
        statement=f"{current.display_name} is the current synthetic version.",
        evidence=(EvidenceLocator(source_id=current.source_id, quote=version_quote),),
    )
    if runtime_result.report.coverage is None:
        raise RuntimeError("offline demo runtime did not produce coverage")
    report_records = render_report_formats(
        ReportDocument(
            title="NemoFold offline demo",
            claims=runtime_result.claims + (version_claim,),
            coverage=runtime_result.report.coverage,
            source_labels=tuple(
                (source.source_id, source.display_name) for source in inventory.records
            ),
        ),
        output,
        basename=run_id,
    )
    bundle_records = (
        ArtifactRecord(
            format="bundle-text",
            path=str(bundle.bundle_path),
            sha256=bundle.bundle_sha256,
        ),
        ArtifactRecord(
            format="bundle-manifest",
            path=str(bundle.manifest_path),
            sha256=bundle.manifest_sha256,
        ),
        ArtifactRecord(
            format="bundle-zip",
            path=str(bundle.zip_path),
            sha256=_file_sha256(bundle.zip_path),
        ),
    )
    report = replace(
        runtime_result.report,
        actions=runtime_result.report.actions
        + ("smart_inbox_move", "smart_inbox_undo", "bundle_export", "report_export"),
        artifacts=report_records + bundle_records + (digest_record, receipt_record),
        metadata={
            **runtime_result.report.metadata,
            "cloud_proof": False,
            "scenario": "normal",
            "version_basis": resolution.basis,
            "version_selected_source_id": resolution.selected.source_id,
            "undo_status": undo_receipt.status,
            "usecases": {
                "UC01": "executed_and_undone",
                "UC03": "policy_preview_executed",
                "UC04": "executed",
                "UC05": "executed",
                "UC06": "offline_executed",
                "UC08": "executed",
                "UC09": "executed",
                "UC14": "offline_executed_cloud_open",
            },
        },
    )
    ledger.update(report)
    return report
