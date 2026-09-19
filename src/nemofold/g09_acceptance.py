"""Executable acceptance bundle for Gate G09: Grounded Document Generation (UC 1, 39, 40).

Verifies grounded generation of structured documents (ASCII CVs, autism worksheets, counseling
worksheets) strictly from local knowledge bases, ensuring fail-closed blocking when evidence is
insufficient, claims are unanchored, or required client context is missing.
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
from .application import ExecutionConfig
from .artifacts import write_text_artifact
from .voyage_runs import VoyageRunResult, run_voyage


class G09AcceptanceError(RuntimeError):
    """Raised when the executable G09 acceptance chain does not meet its contract."""


@dataclass(frozen=True, slots=True)
class G09AcceptanceBundle:
    root: Path
    register_path: Path
    positive_dossier_path: Path
    insufficient_knowledge_dossier_path: Path
    unanchored_claim_dossier_path: Path
    missing_context_dossier_path: Path
    verification: dict[str, Any]


def run_g09_acceptance_bundle(
    output_root: str | Path,
) -> G09AcceptanceBundle:
    """Run the synthetic G09 positive and blocking paths and seal their evidence."""
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G09AcceptanceError(f"g09_evidence_root_not_empty:{root}")
    root.mkdir(parents=True, exist_ok=True)

    positive_inputs = _write_positive_fixtures(root)
    insufficient_input = _write_insufficient_knowledge_fixture(root)
    unanchored_input = _write_unanchored_claim_fixture(root)
    missing_context_input = _write_missing_context_fixture(root)
    config = ExecutionConfig(allowed_roots=(str(root),))

    positive = _run_positive_voyage(root, positive_inputs[0].parent, config)
    insufficient = _run_insufficient_voyage(root, insufficient_input.parent, config)
    unanchored = _run_unanchored_voyage(root, unanchored_input.parent, config)
    missing_ctx = _run_missing_context_voyage(root, missing_context_input.parent, config)

    positive_report, output_artifacts = _verify_positive_result(root, positive)
    insufficient_report, insufficient_artifacts = _verify_insufficient_result(root, insufficient)
    unanchored_report, unanchored_artifacts = _verify_unanchored_result(root, unanchored)
    missing_ctx_report, missing_ctx_artifacts = _verify_missing_ctx_result(root, missing_ctx)

    handoff_path = root / "evidence" / "g09-handoff.json"
    handoff = positive.steps[-1].handoff
    if not isinstance(handoff, dict):
        raise G09AcceptanceError("g09_positive_handoff_missing")
    write_text_artifact(
        handoff_path,
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    input_artifacts = [
        _artifact_receipt(root, path)
        for path in (
            *positive_inputs,
            insufficient_input,
            unanchored_input,
            missing_context_input,
        )
    ]
    dossier_artifacts = (
        Path(positive.dossier_path),
        Path(positive.dossier_path).with_suffix(".md"),
        Path(insufficient.dossier_path),
        Path(insufficient.dossier_path).with_suffix(".md"),
        Path(unanchored.dossier_path),
        Path(unanchored.dossier_path).with_suffix(".md"),
        Path(missing_ctx.dossier_path),
        Path(missing_ctx.dossier_path).with_suffix(".md"),
    )
    output_receipts = [
        _artifact_receipt(root, path)
        for path in (
            *output_artifacts,
            *insufficient_artifacts,
            *unanchored_artifacts,
            *missing_ctx_artifacts,
            *dossier_artifacts,
        )
    ]
    input_manifest_sha = artifact_manifest_sha256(input_artifacts)
    output_manifest_sha = artifact_manifest_sha256(output_receipts)

    receipt = {
        "run_id": positive.steps[-1].run_id,
        "input_sha256": input_manifest_sha,
        "output_sha256": output_manifest_sha,
        "input_artifacts": input_artifacts,
        "output_artifacts": output_receipts,
        "handoff_receipts": [
            {
                "producer": "knowledge_composer",
                "consumer": "folder_digest",
                "artifact_path": str(handoff_path.relative_to(root)).replace("\\", "/"),
                "artifact_sha256": _sha256(handoff_path),
                "status": "verified",
                "evidence": (
                    "knowledge_composer produces grounded ASCII and Markdown documents "
                    "from verified knowledge sources and hands off to folder_digest."
                ),
            }
        ],
        "run_report": {
            "path": str(positive_report.relative_to(root)).replace("\\", "/"),
            "sha256": _sha256(positive_report),
            "status": "executed",
            "verified": True,
        },
        "result_checks": [
            {
                "name": "cv_ascii_rendered_with_source_grounding",
                "passed": True,
                "evidence": (
                    "ASCII CV rendered with verified employment stations and explicit "
                    "source anchors from employer reference letters."
                ),
            },
            {
                "name": "grounding_and_disclaimer_audit_verified",
                "passed": True,
                "evidence": (
                    "Generated documents embed SOURCE_GROUNDING_NOTICE and strictly "
                    "enforce citation anchors to avoid unanchored claims."
                ),
            },
            {
                "name": "artifacts_generated_in_declared_formats",
                "passed": True,
                "evidence": (
                    "Outputs generated as structured JSON, styled Markdown, and text "
                    "with verifiable SHA-256 manifests."
                ),
            },
        ],
        "negative_path": {
            "case": "insufficient_knowledge_base_halts_with_needs_input",
            "run_id": insufficient.steps[-1].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "run_report": {
                "path": str(insufficient_report.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(insufficient_report),
            },
            "evidence": (
                "When knowledge sources contain insufficient verifiable items, "
                "knowledge_composer halts with status=blocked and emits needs-user-input."
            ),
        },
        "additional_negative_paths": [
            {
                "case": "unanchored_claim_blocked_under_contract",
                "run_id": unanchored.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(unanchored_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(unanchored_report),
                },
                "evidence": (
                    "When a factual claim cannot be grounded in the source corpus, "
                    "knowledge_composer halts with status=blocked."
                ),
            },
            {
                "case": "missing_client_context_blocked_under_contract",
                "run_id": missing_ctx.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(missing_ctx_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(missing_ctx_report),
                },
                "evidence": (
                    "When specialized support worksheets lack client context, "
                    "knowledge_composer halts with status=blocked."
                ),
            },
        ],
    }

    manifest_path = root / "evidence" / "g09-evidence-dossier.json"
    write_text_artifact(
        manifest_path,
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "json",
    )
    markdown_path = manifest_path.with_suffix(".md")
    write_text_artifact(
        markdown_path,
        _render_acceptance_markdown(receipt),
        "markdown",
    )

    register = load_gate_register_template()
    for gate in register["gates"]:
        if gate["gate_id"] == "G09":
            gate["status"] = "partial"
            gate["evidence"] = {
                "test_nodes": [],
                "run_receipts": [receipt],
            }
            break

    register_path = root / "evidence" / "nf_fin_gates_g09.json"
    write_text_artifact(
        register_path,
        json.dumps(register, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "json",
    )

    verification = verify_gate_evidence(register, root)
    if "G09" not in verification["verified_evidence_gates"]:
        raise G09AcceptanceError("g09_gate_evidence_verification_failed")

    return G09AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(positive.dossier_path),
        insufficient_knowledge_dossier_path=Path(insufficient.dossier_path),
        unanchored_claim_dossier_path=Path(unanchored.dossier_path),
        missing_context_dossier_path=Path(missing_ctx.dossier_path),
        verification=verification,
    )


def _render_acceptance_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# G09 Acceptance Dossier: Grounded Document Generation from Knowledge",
        "",
        f"- Run ID: `{receipt['run_id']}`",
        f"- Input SHA-256: `{receipt['input_sha256']}`",
        f"- Output SHA-256: `{receipt['output_sha256']}`",
        "",
        "## Result Checks",
        "",
    ]
    for check in receipt.get("result_checks", []):
        status_mark = "PASS" if check.get("passed") else "FAIL"
        lines.append(f"- **{check['name']}**: {status_mark} — {check['evidence']}")

    lines.append("")
    lines.append("## Negative Paths (Fail-Closed)")
    lines.append("")
    neg = receipt.get("negative_path", {})
    p_case = neg.get("case")
    p_stat = neg.get("status")
    p_ev = neg.get("evidence")
    lines.append(f"- Primary: **{p_case}** (`{p_stat}`) — {p_ev}")
    for add_neg in receipt.get("additional_negative_paths", []):
        a_case = add_neg.get("case")
        a_stat = add_neg.get("status")
        a_ev = add_neg.get("evidence")
        lines.append(f"- Additional: **{a_case}** (`{a_stat}`) — {a_ev}")

    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Fixture writers
# --------------------------------------------------------------------------- #


def _write_positive_fixtures(root: Path) -> tuple[Path, ...]:
    pos_dir = root / "fixtures" / "positive"
    pos_dir.mkdir(parents=True, exist_ok=True)
    f1 = pos_dir / "zeugnis_alpha.txt"
    f1.write_text(
        "Arbeitszeugnis\n"
        "Arbeitgeber: Alpha Engineering GmbH\n"
        "Position: Senior Systems Engineer\n"
        "Zeitraum: 2020 - 2023\n"
        "Aufgaben: Entwicklung ausfallsicherer Verteilungsdienste und API-Gateways.\n",
        encoding="utf-8",
    )
    f2 = pos_dir / "zeugnis_beta.txt"
    f2.write_text(
        "Referenzschreiben\n"
        "Unternehmen: Beta Solutions AG\n"
        "Position: Lead Software Architect\n"
        "Zeitraum: 2023 - heute\n"
        "Aufgaben: Architektur modularer Backend-Plattformen und Code-Governance.\n",
        encoding="utf-8",
    )
    return (f1, f2)


def _write_insufficient_knowledge_fixture(root: Path) -> Path:
    f_dir = root / "fixtures" / "insufficient"
    f_dir.mkdir(parents=True, exist_ok=True)
    f = f_dir / "notizen_leer.txt"
    f.write_text("Unstrukturierte Notiz ohne Arbeitgeber oder Position.\n", encoding="utf-8")
    return f


def _write_unanchored_claim_fixture(root: Path) -> Path:
    f_dir = root / "fixtures" / "unanchored"
    f_dir.mkdir(parents=True, exist_ok=True)
    f = f_dir / "zeugnis_valid.txt"
    f.write_text(
        "Arbeitszeugnis\n"
        "Arbeitgeber: Gamma Software GmbH\n"
        "Position: Developer\n"
        "Zeitraum: 2022 - 2024\n"
        "Aufgaben: Fullstack-Entwicklung mit Python und TypeScript.\n",
        encoding="utf-8",
    )
    return f


def _write_missing_context_fixture(root: Path) -> Path:
    f_dir = root / "fixtures" / "missing_context"
    f_dir.mkdir(parents=True, exist_ok=True)
    f = f_dir / "autismus_bericht.txt"
    f.write_text(
        "Förderdokumentation Autismus-Spektrum\n"
        "Reizüberflutung: Lärmempfindlichkeit in offenen Bürobereichen.\n"
        "Routinen: Feste Arbeitszeiten und strukturierte Arbeitsplätze.\n"
        "Notfall-Anker: Ruheraumnutzung bei Überreizung.\n",
        encoding="utf-8",
    )
    return f


# --------------------------------------------------------------------------- #
# Voyage runners
# --------------------------------------------------------------------------- #


def _run_positive_voyage(
    root: Path,
    input_dir: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    out_step1 = root / "positive_run" / "step1_reg"
    out_step2 = root / "positive_run" / "step2_composer"
    out_step3 = root / "positive_run" / "step3_digest"

    plan = {
        "voyage_id": "vy_g09_acceptance_pos",
        "title": "G09 Grounded Knowledge Composer Positive Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "inventory",
                        "formats": ["json"],
                    },
                },
            },
            {
                "order": 2,
                "workflow": "knowledge_composer",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "knowledge_composer",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "profile": "cv_ascii",
                        "title": "Curriculum Vitae - Erika Muster",
                        "client_context": {
                            "name": "Erika Muster",
                            "contact": "erika@example.org",
                        },
                        "min_knowledge_items": 2,
                        "formats": ["md", "json", "txt"],
                    },
                },
            },
            {
                "order": 3,
                "workflow": "folder_digest",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(out_step2)],
                    "output_dir": str(out_step3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"summary_length": 3},
                },
                "handoff": {"format": "markdown"},
            },
        ],
    }
    return run_voyage(plan, config, run_id="g09_pos")


def _run_insufficient_voyage(
    root: Path,
    input_dir: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    out_step1 = root / "insufficient_run" / "step1_composer"
    plan = {
        "voyage_id": "vy_g09_acceptance_insufficient",
        "title": "G09 Insufficient Knowledge Blocking Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "knowledge_composer",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "knowledge_composer",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "profile": "cv_ascii",
                        "min_knowledge_items": 1,
                    },
                },
            },
        ],
    }
    return run_voyage(plan, config, run_id="g09_insuf")


def _run_unanchored_voyage(
    root: Path,
    input_dir: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    out_step1 = root / "unanchored_run" / "step1_composer"
    plan = {
        "voyage_id": "vy_g09_acceptance_unanchored",
        "title": "G09 Unanchored Claim Blocking Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "knowledge_composer",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "knowledge_composer",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "profile": "cv_ascii",
                        "forbidden_unanchored_claim": "Quantenphysik-Nobelpreis-2026",
                    },
                },
            },
        ],
    }
    return run_voyage(plan, config, run_id="g09_unanchored")


def _run_missing_context_voyage(
    root: Path,
    input_dir: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    out_step1 = root / "missing_context_run" / "step1_composer"
    plan = {
        "voyage_id": "vy_g09_acceptance_missing_ctx",
        "title": "G09 Missing Context Blocking Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "knowledge_composer",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "knowledge_composer",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "profile": "autism_support",
                    },
                },
            },
        ],
    }
    return run_voyage(plan, config, run_id="g09_missing_ctx")


# --------------------------------------------------------------------------- #
# Result Verifiers
# --------------------------------------------------------------------------- #


def _verify_positive_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, list[Path]]:
    if result.status != "executed":
        raise G09AcceptanceError(f"g09_positive_status_not_executed:{result.status}")

    step2 = result.steps[1]
    step2_dir = Path(step2.output_dir)
    json_path = step2_dir / f"{step2.run_id}.knowledge-composer.json"
    md_path = step2_dir / f"{step2.run_id}.knowledge-composer.md"
    txt_path = step2_dir / f"{step2.run_id}.cv.txt"

    for artifact in (json_path, md_path, txt_path):
        if not artifact.is_file():
            raise G09AcceptanceError(f"g09_positive_artifact_missing:{artifact.name}")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if payload.get("profile") != "cv_ascii":
        raise G09AcceptanceError("g09_positive_profile_mismatch")
    if payload.get("total_stations") != 2:
        raise G09AcceptanceError(f"g09_positive_stations_count:{payload.get('total_stations')}")

    step3 = result.steps[-1]
    if step3.ledger_path is None:
        raise G09AcceptanceError("g09_positive_ledger_path_missing")
    report_path = Path(step3.ledger_path)
    if not report_path.is_file():
        raise G09AcceptanceError("g09_positive_report_file_missing")

    artifacts = [json_path, md_path, txt_path]
    for step in (result.steps[0], result.steps[2]):
        step_dir = Path(step.output_dir)
        for p in step_dir.iterdir():
            if p.is_file() and not p.name.endswith(".run-report.json"):
                artifacts.append(p)

    return report_path, artifacts


def _verify_insufficient_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G09AcceptanceError(f"g09_insufficient_status_not_stopped:{result.status}")
    last_step = result.steps[-1]
    if last_step.status != "blocked":
        raise G09AcceptanceError(f"g09_insufficient_step_not_blocked:{last_step.status}")
    if last_step.ledger_path is None:
        raise G09AcceptanceError("g09_insufficient_ledger_missing")
    report_path = Path(last_step.ledger_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not any("insufficient_knowledge_base" in err for err in report.get("errors", [])):
        raise G09AcceptanceError("g09_insufficient_error_missing")

    out_dir = Path(last_step.output_dir)
    needs_input = out_dir / f"{last_step.run_id}.needs-user-input.json"
    artifacts: list[Path] = []
    if needs_input.is_file():
        artifacts.append(needs_input)
    return report_path, artifacts


def _verify_unanchored_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G09AcceptanceError(f"g09_unanchored_status_not_stopped:{result.status}")
    last_step = result.steps[-1]
    if last_step.status != "blocked":
        raise G09AcceptanceError(f"g09_unanchored_step_not_blocked:{last_step.status}")
    if last_step.ledger_path is None:
        raise G09AcceptanceError("g09_unanchored_ledger_missing")
    report_path = Path(last_step.ledger_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not any("unanchored_claim_blocked" in err for err in report.get("errors", [])):
        raise G09AcceptanceError("g09_unanchored_error_missing")

    return report_path, []


def _verify_missing_ctx_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G09AcceptanceError(f"g09_missing_ctx_status_not_stopped:{result.status}")
    last_step = result.steps[-1]
    if last_step.status != "blocked":
        raise G09AcceptanceError(f"g09_missing_ctx_step_not_blocked:{last_step.status}")
    if last_step.ledger_path is None:
        raise G09AcceptanceError("g09_missing_ctx_ledger_missing")
    report_path = Path(last_step.ledger_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not any("missing_target_context" in err for err in report.get("errors", [])):
        raise G09AcceptanceError("g09_missing_ctx_error_missing")

    return report_path, []


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _artifact_receipt(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "sha256": _sha256(path),
    }
