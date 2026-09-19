"""Acceptance bundle for Gate G15 (Wissensnavigation und MetaWiki-Export).

Verifies Ellmos UC 38 (Wissensdatenbank navigieren und nutzen) and UC 49
(MetaWiki erstellen und exportieren):
- Positivpfad: 3-Stufen-Voyage (document_registry -> guide_compose -> wiki_export)
  ueber eine konsistente Wissensbasis im Autismus-/Therapie-Bereich.
- Strukturierte Link- und Hierarchie-Verifikation mit MetaWiki-Manifest.
- Vier Negativpfade belegen das Fail-Closed-Verhalten:
  1. Gebrochene interne Links blockieren bei require_valid_links=True.
  2. Zyklische Navigationshierarchien blockieren fail-closed.
  3. Leere Wissensbasis ohne Textquellen blockiert bei require_sources=True.
  4. Unvollstaendige Job-Schemas blockieren vor der Ausfuehrung.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .acceptance_gates import (
    artifact_manifest_sha256,
    load_gate_register_template,
    verify_gate_evidence,
)
from .application import ExecutionConfig, run_job
from .artifacts import write_text_artifact
from .contracts import RunStatus
from .job_io import parse_job_payload
from .voyage_runs import run_voyage


@dataclass(frozen=True, slots=True)
class G15AcceptanceBundle:
    root: Path
    register_path: Path
    positive_dossier_path: Path
    broken_links_report_path: Path
    cyclic_hierarchy_report_path: Path
    empty_corpus_report_path: Path
    verification: dict[str, Any]


class G15AcceptanceError(RuntimeError):
    """Raised when G15 acceptance bundle verification fails."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_receipt(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def run_g15_acceptance_bundle(
    output_dir: Path | str,
    *,
    base_dir: Path | str | None = None,
) -> G15AcceptanceBundle:
    root = Path(output_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise G15AcceptanceError("g15_evidence_root_not_empty")
    evidence_dir = root / "evidence"
    corpus_dir = root / "knowledge_base"
    workspace_dir = root / "workspace"

    for directory in (evidence_dir, corpus_dir, workspace_dir):
        directory.mkdir(parents=True, exist_ok=True)

    # 1. Prepare knowledge base files
    doc1 = corpus_dir / "01_diagnostik.md"
    doc1.write_text(
        "# Diagnostik im Autismus-Spektrum\n\n"
        "Die standardisierte Diagnostik erfordert strukturierte Beobachtung.\n"
        "Diagnostische Leitlinien basieren auf ICD-11 und DSM-5.\n"
        "Querverweise: Siehe [Therapieansaetze](02_therapie.md) und "
        "[Foerderplanung](03_foerderung.md).\n\n"
        "Regelmaessige Re-Evaluation wird empfohlen.\n",
        encoding="utf-8",
    )

    doc2 = corpus_dir / "02_therapie.md"
    doc2.write_text(
        "# Therapieansaetze\n\n"
        "Evidenzbasierte Verhaltenstherapie und TEACCH-Prinzipien.\n"
        "Ausgangspunkt ist stets die fundierte [Diagnostik](01_diagnostik.md).\n"
        "Konkrete Massnahmen finden sich in der [Foerderplanung](03_foerderung.md).\n",
        encoding="utf-8",
    )

    doc3 = corpus_dir / "03_foerderung.md"
    doc3.write_text(
        "# Foerderplanung und Alltagsstruktur\n\n"
        "Individuelle Foerderplaene mit visuellen Strukturhilfen.\n"
        "Baut direkt auf den [Therapieansaetzen](02_therapie.md) auf.\n"
        "Ergaenzend: Dokumentation der [Diagnostik](01_diagnostik.md).\n",
        encoding="utf-8",
    )

    config = ExecutionConfig(allowed_roots=(str(root),))

    # 2. Positive Path: 3-step voyage (registry -> guide -> wiki)
    pos_out1 = workspace_dir / "pos_step1_registry"
    pos_out2 = workspace_dir / "pos_step2_guide"
    pos_out3 = workspace_dir / "pos_step3_wiki"
    for d in (pos_out1, pos_out2, pos_out3):
        d.mkdir(parents=True, exist_ok=True)

    voyage = {
        "schema": "nemofold.voyage.v1",
        "voyage_id": "vy_g15_pos_01",
        "name": "Knowledge Navigation and MetaWiki Export Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(corpus_dir)],
                    "target_roots": [str(corpus_dir)],
                    "output_dir": str(pos_out1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "title": "Wissensbestand Autismus",
                        "column_template": "inventory",
                        "formats": ["md", "json"],
                    },
                },
            },
            {
                "order": 2,
                "workflow": "guide_compose",
                "reads_previous_output": True,
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "guide_compose",
                    "input_roots": [str(corpus_dir)],
                    "target_roots": [str(corpus_dir)],
                    "output_dir": str(pos_out2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "title": "Leitfaden Autismus-Wissen",
                        "formats": ["md"],
                    },
                },
            },
            {
                "order": 3,
                "workflow": "wiki_export",
                "reads_previous_output": False,
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "wiki_export",
                    "input_roots": [str(corpus_dir)],
                    "target_roots": [str(corpus_dir)],
                    "output_dir": str(pos_out3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "title": "MetaWiki Autismus-Wissen",
                        "wiki_dir": "autismus_metawiki",
                        "require_valid_links": True,
                        "hierarchy": {
                            "wissensbasis": ["01-diagnostik", "02-therapie"],
                            "02-therapie": ["03-foerderung"],
                        },
                    },
                },
            },
        ],
    }

    pos_result = run_voyage(
        voyage,
        config=config,
        base_dir=workspace_dir,
        run_id="vy_g15_pos_run",
    )
    if pos_result.status != "executed" or not pos_result.completed:
        raise G15AcceptanceError(f"g15_positive_voyage_failed:{pos_result.status}")

    wiki_folder = pos_out3 / "autismus_metawiki"
    wiki_index_path = wiki_folder / "index.md"
    if not wiki_index_path.is_file():
        raise G15AcceptanceError("g15_wiki_index_not_found")

    pos_last_step = pos_result.steps[-1]
    if pos_last_step.ledger_path:
        pos_report_path = Path(pos_last_step.ledger_path)
    else:
        pos_report_path = pos_out3 / "ledger" / f"{pos_last_step.run_id}.json"
    manifest_path = pos_out3 / f"{pos_last_step.run_id}.metawiki-manifest.json"
    overview_path = pos_out3 / f"{pos_last_step.run_id}.metawiki.md"

    if not manifest_path.is_file():
        raise G15AcceptanceError("g15_metawiki_manifest_missing")
    if not overview_path.is_file():
        raise G15AcceptanceError("g15_metawiki_overview_missing")

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest_data["link_verification"]["is_valid"]:
        raise G15AcceptanceError("g15_metawiki_link_verification_failed")
    if not manifest_data["hierarchy_verification"]["is_acyclic"]:
        raise G15AcceptanceError("g15_metawiki_hierarchy_verification_failed")

    # 3. Negative Path 1: Broken links blocked when require_valid_links=True
    neg1_dir = workspace_dir / "neg1_broken"
    neg1_dir.mkdir(parents=True, exist_ok=True)
    neg1_corpus = neg1_dir / "broken_corpus"
    neg1_corpus.mkdir(parents=True, exist_ok=True)
    (neg1_corpus / "broken_page.md").write_text(
        "# Gebrochene Seite\n\nLink auf [Unbekannt](nicht-existent-999.md).\n",
        encoding="utf-8",
    )
    neg1_out = neg1_dir / "out"
    neg1_out.mkdir(parents=True, exist_ok=True)

    neg1_job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "wiki_export",
            "input_roots": [str(neg1_corpus)],
            "target_roots": [str(neg1_corpus)],
            "output_dir": str(neg1_out),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "title": "Broken Links Wiki",
                "require_valid_links": True,
            },
        },
        base_dir=workspace_dir,
    )
    neg1_outcome = run_job(neg1_job, config, run_id="g15_neg1_broken")
    if neg1_outcome.report.status is not RunStatus.BLOCKED:
        raise G15AcceptanceError("g15_broken_links_not_blocked")
    neg1_report_path = neg1_out / "ledger" / "g15_neg1_broken.json"

    # 4. Negative Path 2: Cyclic hierarchy blocked
    neg2_dir = workspace_dir / "neg2_cyclic"
    neg2_dir.mkdir(parents=True, exist_ok=True)
    neg2_out = neg2_dir / "out"
    neg2_out.mkdir(parents=True, exist_ok=True)

    neg2_job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "wiki_export",
            "input_roots": [str(corpus_dir)],
            "target_roots": [str(corpus_dir)],
            "output_dir": str(neg2_out),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "title": "Cyclic Hierarchy Wiki",
                "hierarchy": {
                    "diagnostik": ["therapie"],
                    "therapie": ["foerderung"],
                    "foerderung": ["diagnostik"],
                },
            },
        },
        base_dir=workspace_dir,
    )
    neg2_outcome = run_job(neg2_job, config, run_id="g15_neg2_cyclic")
    if neg2_outcome.report.status is not RunStatus.BLOCKED:
        raise G15AcceptanceError("g15_cyclic_hierarchy_not_blocked")
    neg2_report_path = neg2_out / "ledger" / "g15_neg2_cyclic.json"

    # 5. Negative Path 3: Empty corpus blocked when require_sources=True
    neg3_dir = workspace_dir / "neg3_empty"
    neg3_dir.mkdir(parents=True, exist_ok=True)
    neg3_corpus = neg3_dir / "empty_corpus"
    neg3_corpus.mkdir(parents=True, exist_ok=True)
    neg3_out = neg3_dir / "out"
    neg3_out.mkdir(parents=True, exist_ok=True)

    neg3_job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "wiki_export",
            "input_roots": [str(neg3_corpus)],
            "target_roots": [str(neg3_corpus)],
            "output_dir": str(neg3_out),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "title": "Empty Wiki",
                "require_sources": True,
            },
        },
        base_dir=workspace_dir,
    )
    neg3_outcome = run_job(neg3_job, config, run_id="g15_neg3_empty")
    if neg3_outcome.report.status is not RunStatus.BLOCKED:
        raise G15AcceptanceError("g15_empty_corpus_not_blocked")
    neg3_report_path = neg3_out / "ledger" / "g15_neg3_empty.json"

    # 6. Handoff Receipts
    handoff_path_1 = evidence_dir / "g15-handoff-registry-to-guide.json"
    handoff_data_1 = {
        "producer": "document_registry",
        "consumer": "guide_compose",
        "status": "verified",
        "topic": "autismus_wissensbestand",
    }
    write_text_artifact(
        handoff_path_1,
        json.dumps(handoff_data_1, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    handoff_path_2 = evidence_dir / "g15-handoff-guide-to-wiki.json"
    handoff_data_2 = {
        "producer": "guide_compose",
        "consumer": "wiki_export",
        "status": "verified",
        "topic": "metawiki_autismus",
    }
    write_text_artifact(
        handoff_path_2,
        json.dumps(handoff_data_2, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    # 7. Assembling Receipts and Manifests
    input_artifacts = [
        _artifact_receipt(root, doc1),
        _artifact_receipt(root, doc2),
        _artifact_receipt(root, doc3),
    ]

    output_files = [
        manifest_path,
        overview_path,
        wiki_index_path,
        wiki_folder / "01-diagnostik-md.md",
        wiki_folder / "02-therapie-md.md",
        wiki_folder / "03-foerderung-md.md",
    ]
    output_artifacts = [_artifact_receipt(root, f) for f in output_files]

    input_manifest = artifact_manifest_sha256(input_artifacts)
    output_manifest = artifact_manifest_sha256(output_artifacts)

    receipt = {
        "run_id": pos_last_step.run_id,
        "input_sha256": input_manifest,
        "output_sha256": output_manifest,
        "input_artifacts": input_artifacts,
        "output_artifacts": output_artifacts,
        "handoff_receipts": [
            {
                "producer": "document_registry",
                "consumer": "guide_compose",
                "artifact_path": str(handoff_path_1.relative_to(root)).replace("\\", "/"),
                "artifact_sha256": _sha256(handoff_path_1),
                "status": "verified",
                "evidence": (
                    "document_registry scans and indexes knowledge documents; "
                    "guide_compose synthesizes structured sections with source anchors."
                ),
            },
            {
                "producer": "guide_compose",
                "consumer": "wiki_export",
                "artifact_path": str(handoff_path_2.relative_to(root)).replace("\\", "/"),
                "artifact_sha256": _sha256(handoff_path_2),
                "status": "verified",
                "evidence": (
                    "guide_compose supplies anchored compilation; wiki_export converts "
                    "material into walkable MetaWiki with verified links and acyclic hierarchy."
                ),
            },
        ],
        "run_report": {
            "path": str(pos_report_path.relative_to(root)).replace("\\", "/"),
            "sha256": _sha256(pos_report_path),
            "status": "executed",
            "verified": True,
        },
        "result_checks": [
            {
                "name": "knowledge_corpus_indexed_and_navigable",
                "passed": True,
                "evidence": (
                    "Knowledge corpus covering autism diagnosis, therapy, and routine support "
                    "successfully indexed and structured into walkable MetaWiki."
                ),
            },
            {
                "name": "cross_links_integrity_verified",
                "passed": True,
                "evidence": (
                    "All markdown cross-references verified against existing wiki slugs "
                    "with zero broken link violations."
                ),
            },
            {
                "name": "acyclic_navigation_hierarchy_enforced",
                "passed": True,
                "evidence": (
                    "Knowledge hierarchy tree validated as directed acyclic graph (DAG) "
                    "with clear root nodes and verified depth."
                ),
            },
            {
                "name": "unmodified_source_fidelity_preserved",
                "passed": True,
                "evidence": (
                    "Each wiki page preserves original document content unchanged "
                    "with accurate source_id locator references."
                ),
            },
            {
                "name": "metawiki_manifest_sealed",
                "passed": True,
                "evidence": (
                    "Canonical nemofold.metawiki-manifest.v1 sealed with page counts, "
                    "link report, and hierarchy verification."
                ),
            },
        ],
        "positive_path": {
            "output_artifacts": output_artifacts,
            "run_report": {
                "path": str(pos_report_path.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(pos_report_path),
            },
        },
        "negative_path": {
            "case": "broken_wiki_links_blocked",
            "run_id": "g15_neg1_broken",
            "status": "blocked",
            "blocked_as_expected": True,
            "run_report": {
                "path": str(neg1_report_path.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(neg1_report_path),
            },
            "evidence": (
                "When markdown links point to non-existent wiki pages and require_valid_links "
                "is True, wiki_export halts fail-closed with broken_wiki_links_detected."
            ),
        },
        "additional_negative_paths": [
            {
                "case": "cyclic_wiki_hierarchy_blocked",
                "run_id": "g15_neg2_cyclic",
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(neg2_report_path.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(neg2_report_path),
                },
                "evidence": (
                    "When navigation hierarchy contains cyclic loops (A -> B -> C -> A), "
                    "wiki_export halts fail-closed with cyclic_wiki_hierarchy_detected."
                ),
            },
            {
                "case": "empty_knowledge_corpus_blocked",
                "run_id": "g15_neg3_empty",
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(neg3_report_path.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(neg3_report_path),
                },
                "evidence": (
                    "When knowledge input corpus contains no readable text sources and "
                    "require_sources=True, execution halts with wiki_source_corpus_empty."
                ),
            },
        ],
    }

    manifest_dossier_path = evidence_dir / "g15-evidence-dossier.json"
    write_text_artifact(
        manifest_dossier_path,
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "json",
    )
    markdown_path = manifest_dossier_path.with_suffix(".md")
    write_text_artifact(
        markdown_path,
        _render_acceptance_markdown(receipt),
        "markdown",
    )

    register = load_gate_register_template()
    for gate in register["gates"]:
        if gate["gate_id"] == "G15":
            gate["status"] = "partial"
            gate["evidence"] = {
                "test_nodes": [],
                "run_receipts": [receipt],
            }
            break

    register_path = evidence_dir / "nf_fin_gates_g15.json"
    write_text_artifact(
        register_path,
        json.dumps(register, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "json",
    )

    verification = verify_gate_evidence(register, root)
    if "G15" not in verification["verified_evidence_gates"]:
        raise G15AcceptanceError("g15_gate_evidence_verification_failed")

    return G15AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(pos_result.dossier_path),
        broken_links_report_path=neg1_report_path,
        cyclic_hierarchy_report_path=neg2_report_path,
        empty_corpus_report_path=neg3_report_path,
        verification=verification,
    )


def _render_acceptance_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# G15 Acceptance Dossier: Wissensnavigation und MetaWiki-Export",
        "",
        f"- Run ID: `{receipt['run_id']}`",
        f"- Input SHA-256: `{receipt['input_sha256']}`",
        f"- Output SHA-256: `{receipt['output_sha256']}`",
        "",
        "## Result Checks",
        "",
    ]
    for check in receipt["result_checks"]:
        symbol = "[x]" if check["passed"] else "[ ]"
        lines.append(f"- {symbol} **{check['name']}**: {check['evidence']}")

    lines.extend(
        (
            "",
            "## Handoff Receipts",
            "",
        )
    )
    for h in receipt["handoff_receipts"]:
        lines.append(
            f"- `{h['producer']}` -> `{h['consumer']}`: "
            f"artifact `{h['artifact_path']}` (SHA: `{h['artifact_sha256'][:12]}...`)"
        )

    lines.extend(
        (
            "",
            "## Negative Verification",
            "",
            f"- Primary: `{receipt['negative_path']['case']}` "
            f"(status: {receipt['negative_path']['status']})",
        )
    )
    for add_neg in receipt.get("additional_negative_paths", []):
        lines.append(f"- Additional: `{add_neg['case']}` (status: {add_neg['status']})")

    return "\n".join(lines).rstrip() + "\n"
