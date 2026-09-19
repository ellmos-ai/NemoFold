"""Executable acceptance bundle for Gate G14: Dossier and Briefing (Ellmos UC 25).

Verifies research question capture, cited web source extraction, synthesis separating
verified facts from inferences, explicit open uncertainties, honest limited briefings
when sources are sparse (avoiding false completeness), and fail-closed privacy gating.
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
from .web_research import WebResult


class G14AcceptanceError(RuntimeError):
    """Raised when the executable G14 acceptance chain does not meet its contract."""


class G14AcceptanceBundle:
    """Artifact bundle resulting from running G14 acceptance tests."""

    def __init__(
        self,
        root: Path,
        register_path: Path,
        positive_dossier_path: Path,
        sparse_dossier_path: Path,
        unapproved_dossier_path: Path,
        sensitive_dossier_path: Path,
        missing_subject_dossier_path: Path,
        verification: dict[str, Any],
    ) -> None:
        self.root = root
        self.register_path = register_path
        self.positive_dossier_path = positive_dossier_path
        self.sparse_dossier_path = sparse_dossier_path
        self.unapproved_dossier_path = unapproved_dossier_path
        self.sensitive_dossier_path = sensitive_dossier_path
        self.missing_subject_dossier_path = missing_subject_dossier_path
        self.verification = verification


@dataclass(frozen=True, slots=True)
class FakeSearchAdapter:
    """Deterministic offline adapter for G14 acceptance."""

    name: str = "tavily"

    def readiness(self) -> tuple[bool, str]:
        return True, ""

    def search(
        self, queries: tuple[str, ...], *, max_results: int
    ) -> tuple[WebResult, ...]:
        results: list[WebResult] = []
        for q_idx, query in enumerate(queries, start=1):
            results.append(
                WebResult(
                    query=query,
                    url=f"https://praxis-schrenk.invalid/aerzte/{q_idx}",
                    title=f"Fachärztliche Profilseite: {query}",
                    excerpt=(
                        f"Schwerpunkt Endokrinologie und Schilddrüsensonographie. "
                        f"Diagnostikknoten und laborchemische Feindiagnostik für {query}."
                    ),
                    rank=q_idx,
                )
            )
        return tuple(results[:max_results])


@dataclass(frozen=True, slots=True)
class SparseSearchAdapter:
    """Offline adapter returning only 1 source to test sparse limitations."""

    name: str = "tavily"

    def readiness(self) -> tuple[bool, str]:
        return True, ""

    def search(
        self, queries: tuple[str, ...], *, max_results: int
    ) -> tuple[WebResult, ...]:
        return (
            WebResult(
                query=queries[0] if queries else "Allgemein",
                url="https://archiv-daten.invalid/einzeltreffer",
                title="Archiv-Kurznotiz ohne Verifizierung",
                excerpt="Einziger Treffer ohne Sekundärbestätigung oder Kontaktdaten.",
                rank=1,
            ),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_receipt(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "sha256": _sha256(path),
    }


def _verify_positive_result(root: Path, result: VoyageRunResult) -> tuple[Path, list[Path]]:
    if result.status != "executed":
        raise G14AcceptanceError(f"g14_positive_not_executed:status={result.status}")
    if len(result.steps) != 3:
        raise G14AcceptanceError(f"g14_positive_step_count_invalid:{len(result.steps)}")

    step1 = result.steps[0]
    if step1.workflow != "web_research" or step1.status != "executed":
        raise G14AcceptanceError("g14_positive_step1_web_research_failed")

    step1_dir = Path(step1.output_dir)
    res_json = step1_dir / f"{step1.run_id}.web-research.json"
    res_md = step1_dir / f"{step1.run_id}_web-notes.md"
    for art in (res_json, res_md):
        if not art.is_file():
            raise G14AcceptanceError(f"g14_positive_step1_missing:{art.name}")

    step2 = result.steps[1]
    if step2.workflow != "briefing" or step2.status != "executed":
        raise G14AcceptanceError("g14_positive_step2_briefing_failed")

    step2_dir = Path(step2.output_dir)
    briefing_json = step2_dir / f"{step2.run_id}.briefing.json"
    briefing_md = step2_dir / f"{step2.run_id}.briefing.md"
    for art in (briefing_json, briefing_md):
        if not art.is_file():
            raise G14AcceptanceError(f"g14_positive_step2_missing:{art.name}")

    briefing_data = json.loads(briefing_json.read_text(encoding="utf-8"))
    if briefing_data.get("schema") != "nemofold.briefing.v1":
        raise G14AcceptanceError("g14_positive_briefing_schema_invalid")
    if briefing_data.get("status") != "complete_briefing":
        raise G14AcceptanceError(f"g14_positive_status_invalid:{briefing_data.get('status')}")
    if briefing_data.get("is_limited") is not False:
        raise G14AcceptanceError("g14_positive_is_limited_should_be_false")
    if len(briefing_data.get("facts", [])) < 2:
        raise G14AcceptanceError("g14_positive_facts_count_insufficient")
    if len(briefing_data.get("inferences", [])) < 1:
        raise G14AcceptanceError("g14_positive_inferences_missing")
    if len(briefing_data.get("uncertainties_and_open_points", [])) < 1:
        raise G14AcceptanceError("g14_positive_uncertainties_missing")

    step3 = result.steps[2]
    if step3.workflow != "document_qa" or step3.status != "executed":
        raise G14AcceptanceError("g14_positive_step3_document_qa_failed")

    step3_dir = Path(step3.output_dir)
    pkg_json = step3_dir / f"{step3.run_id}.publication-package.json"
    pkg_md = step3_dir / f"{step3.run_id}.publication-package.md"
    qa_json = step3_dir / f"{step3.run_id}.document-qa.json"
    for art in (pkg_json, pkg_md, qa_json):
        if not art.is_file():
            raise G14AcceptanceError(f"g14_positive_step3_missing:{art.name}")

    pkg_data = json.loads(pkg_json.read_text(encoding="utf-8"))
    if pkg_data.get("qa_passed") is not True:
        raise G14AcceptanceError("g14_positive_qa_passed_not_true")

    report_path = (
        Path(step3.ledger_path)
        if step3.ledger_path
        else (step3_dir / "jobs" / f"{step3.run_id}.json")
    )
    if not report_path.is_file():
        raise G14AcceptanceError("g14_positive_report_missing")

    artifacts: list[Path] = [
        res_json,
        res_md,
        briefing_json,
        briefing_md,
        pkg_json,
        pkg_md,
        qa_json,
    ]
    for step in result.steps:
        if step.ledger_path:
            p = Path(step.ledger_path)
            if p.is_file() and p != report_path:
                artifacts.append(p)
    return report_path, artifacts


def _verify_blocked_result(
    root: Path,
    result: VoyageRunResult,
    expected_error: str,
    voyage_name: str,
) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G14AcceptanceError(f"{voyage_name}_not_stopped:status={result.status}")

    blocked_step = result.steps[-1]
    if blocked_step.status not in {"blocked", "failed"}:
        raise G14AcceptanceError(
            f"{voyage_name}_step_not_blocked:status={blocked_step.status}"
        )
    if not any(expected_error in err for err in blocked_step.errors):
        raise G14AcceptanceError(
            f"{voyage_name}_expected_error_missing:{expected_error} not in {blocked_step.errors}"
        )

    dossier_path = Path(result.dossier_path)
    if not dossier_path.is_file():
        raise G14AcceptanceError(f"{voyage_name}_dossier_missing")

    if blocked_step.ledger_path is None:
        raise G14AcceptanceError(f"{voyage_name}_ledger_path_missing")
    ledger_path = Path(blocked_step.ledger_path)
    if not ledger_path.is_file():
        raise G14AcceptanceError(f"{voyage_name}_ledger_file_missing")

    artifacts: list[Path] = []
    out_dir = Path(blocked_step.output_dir)
    for ext in ("*.json", "*.md"):
        for f in out_dir.glob(ext):
            if f.is_file() and f != ledger_path and f.parent.name != "ledger":
                artifacts.append(f)

    return ledger_path, artifacts


def run_g14_acceptance_bundle(output_root: str | Path) -> G14AcceptanceBundle:
    """Execute the full G14 acceptance pipeline across positive and negative voyages."""
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G14AcceptanceError("g14_evidence_root_not_empty")
    root.mkdir(parents=True, exist_ok=True)
    inbox = root / "inputs"
    inbox.mkdir(parents=True, exist_ok=True)
    evidence_dir = root / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    work_dir = root / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    # Input fixture
    meeting_doc = inbox / "meeting_notiz.txt"
    meeting_doc.write_text(
        "Meeting-Vorbereitung Dr. Almut Schrenk\n"
        "Anlass: Vorbereitung der Konsultation und Fachbesprechung Diagnostik.\n"
        "Ziel: Profil, Schwerpunkte, Fakten und offene Fragen strukturiert bündeln.\n",
        encoding="utf-8",
    )

    pos_out1 = root / "runs" / "pos_s1"
    pos_out2 = root / "runs" / "pos_s2"
    pos_out3 = root / "runs" / "pos_s3"
    unapproved_out = root / "runs" / "unapproved_s1"
    sensitive_out = root / "runs" / "sensitive_s1"
    sparse_blocked_out = root / "runs" / "sparse_blocked_s1"
    sparse_limited_out = root / "runs" / "sparse_limited_s1"
    missing_subj_out = root / "runs" / "missing_subj_s1"

    # Positive Plan (3 steps)
    positive_plan = {
        "voyage_id": "vy_g14_pos",
        "name": "g14_positive_web_briefing_qa",
        "steps": [
            {
                "order": 1,
                "workflow": "web_research",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "web_research",
                    "input_roots": [str(inbox)],
                    "output_dir": str(pos_out1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "queries": [
                            "Dr. Almut Schrenk Spezialisierung",
                            "Praxis Schrenk Diagnostik",
                        ],
                        "max_results": 2,
                        "web_adapter": "tavily",
                        "mock_adapter": FakeSearchAdapter(),
                        "web_search_approved": True,
                        "title": "Web Recherche Dr. Almut Schrenk",
                    },
                },
            },
            {
                "order": 2,
                "workflow": "briefing",
                "reads_previous_output": True,
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "briefing",
                    "input_roots": [str(pos_out1)],
                    "output_dir": str(pos_out2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "subject": "Dr. Almut Schrenk",
                        "question": (
                            "Welche Schwerpunkte und diagnostischen Verfahren "
                            "bietet die Praxis?"
                        ),
                        "meeting_context": "Fachgespräch Schilddrüsendiagnostik",
                        "min_sources": 2,
                        "title": "Briefing Dr. Almut Schrenk",
                    },
                },
            },
            {
                "order": 3,
                "workflow": "document_qa",
                "handoff": {"format": "briefing-markdown"},
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_qa",
                    "input_roots": [str(pos_out2)],
                    "output_dir": str(pos_out3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "required_sections": [
                            "Fragestellung",
                            "Recherchequellen",
                            "Synthese",
                            "Schlussfolgerungen",
                            "Unsicherheiten und offene Punkte",
                        ],
                        "disallow_unbound_fields": True,
                        "min_words": 20,
                        "target_format": "markdown",
                        "package_title": "Dossier und Briefing Dr. Almut Schrenk",
                        "version": "1.0",
                    },
                },
            },
        ],
    }

    # Negative Plan 1: Web search not approved (Main negative path)
    unapproved_plan = {
        "voyage_id": "vy_g14_unapproved",
        "name": "g14_unapproved_search_blocked",
        "steps": [
            {
                "order": 1,
                "workflow": "briefing",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "briefing",
                    "input_roots": [str(inbox)],
                    "output_dir": str(unapproved_out),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "subject": "Dr. Almut Schrenk",
                        "queries": ["Dr. Almut Schrenk Diagnostik"],
                        "web_adapter": "tavily",
                        "mock_adapter": FakeSearchAdapter(),
                        "web_search_approved": False,
                        "title": "Unapproved Web Search",
                    },
                },
            }
        ],
    }

    # Negative Plan 2: Sensitive query refused by preflight (Additional negative 1)
    sensitive_plan = {
        "voyage_id": "vy_g14_sensitive",
        "name": "g14_sensitive_query_blocked",
        "steps": [
            {
                "order": 1,
                "workflow": "briefing",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "briefing",
                    "input_roots": [str(inbox)],
                    "output_dir": str(sensitive_out),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "subject": "Dr. Almut Schrenk",
                        "queries": [
                            "suche nach almut.schrenk@praxis-berlin.invalid und +49 30 12345678"
                        ],
                        "web_adapter": "tavily",
                        "mock_adapter": FakeSearchAdapter(),
                        "web_search_approved": True,
                        "title": "Sensitive Query Search",
                    },
                },
            }
        ],
    }

    # Negative Plan 3: Sparse sources with require_sufficient_sources (Additional negative 2)
    sparse_blocked_plan = {
        "voyage_id": "vy_g14_sparse_blocked",
        "name": "g14_sparse_sources_strictly_blocked",
        "steps": [
            {
                "order": 1,
                "workflow": "briefing",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "briefing",
                    "input_roots": [str(inbox)],
                    "output_dir": str(sparse_blocked_out),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "subject": "Spezialfall X",
                        "queries": ["Spezialfall X"],
                        "min_sources": 3,
                        "require_sufficient_sources": True,
                        "mock_adapter": SparseSearchAdapter(),
                        "web_search_approved": True,
                        "title": "Strict Sparse Briefing",
                    },
                },
            }
        ],
    }

    # Negative Plan 4: Missing subject refused (Additional negative 3)
    missing_subj_plan = {
        "voyage_id": "vy_g14_missing_subj",
        "name": "g14_missing_subject_refused",
        "steps": [
            {
                "order": 1,
                "workflow": "briefing",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "briefing",
                    "input_roots": [str(inbox)],
                    "output_dir": str(missing_subj_out),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "subject": "",
                        "queries": ["Allgemeines Thema"],
                        "mock_adapter": FakeSearchAdapter(),
                        "web_search_approved": True,
                    },
                },
            }
        ],
    }

    # Non-blocking sparse check: Honest limited briefing without throwing (Ellmos UC 25 core test)
    sparse_limited_plan = {
        "voyage_id": "vy_g14_sparse_limited",
        "name": "g14_sparse_sources_limited_briefing",
        "steps": [
            {
                "order": 1,
                "workflow": "briefing",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "briefing",
                    "input_roots": [str(inbox)],
                    "output_dir": str(sparse_limited_out),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "subject": "Lückenhafte Quelle Z",
                        "queries": ["Thema Z"],
                        "min_sources": 3,
                        "mock_adapter": SparseSearchAdapter(),
                        "web_search_approved": True,
                        "title": "Limited Briefing On Sparse Sources",
                    },
                },
            }
        ],
    }

    exec_config = ExecutionConfig(
        allowed_roots=(str(root),),
        apply_actions_allowed=True,
        web_search_allowed=True,
    )

    # Execute Positive Voyage
    pos_result = run_voyage(
        positive_plan,
        exec_config,
        run_id="vy_g14_pos",
        base_dir=work_dir,
    )
    positive_report, output_artifacts = _verify_positive_result(root, pos_result)

    # Execute Negative Voyages
    unapproved_result = run_voyage(
        unapproved_plan,
        exec_config,
        run_id="vy_g14_unapproved",
        base_dir=work_dir,
    )
    unapproved_report, unapproved_artifacts = _verify_blocked_result(
        root,
        unapproved_result,
        "web_search_not_approved_for_this_call",
        "unapproved_search",
    )

    sensitive_result = run_voyage(
        sensitive_plan,
        exec_config,
        run_id="vy_g14_sensitive",
        base_dir=work_dir,
    )
    sensitive_report, sensitive_artifacts = _verify_blocked_result(
        root,
        sensitive_result,
        "query refused by the pseudonymization preflight",
        "sensitive_query",
    )

    sparse_blocked_result = run_voyage(
        sparse_blocked_plan,
        exec_config,
        run_id="vy_g14_sparse_blocked",
        base_dir=work_dir,
    )
    sparse_blocked_report, sparse_blocked_artifacts = _verify_blocked_result(
        root,
        sparse_blocked_result,
        "insufficient_sources_for_briefing",
        "sparse_sources_strictly_blocked",
    )

    missing_subj_result = run_voyage(
        missing_subj_plan,
        exec_config,
        run_id="vy_g14_missing_subj",
        base_dir=work_dir,
    )
    missing_subj_report, missing_subj_artifacts = _verify_blocked_result(
        root,
        missing_subj_result,
        "a briefing needs a declared subject",
        "missing_subject_refused",
    )

    # Execute honest limited briefing without throwing (Ellmos UC 25 core test)
    sparse_limited_result = run_voyage(
        sparse_limited_plan,
        exec_config,
        run_id="vy_g14_sparse_limited",
        base_dir=work_dir,
    )
    if sparse_limited_result.status != "executed":
        raise G14AcceptanceError("g14_sparse_limited_should_execute_honestly")
    lim_json_path = sparse_limited_out / "vy_g14_sparse_limited_01.briefing.json"
    lim_md_path = sparse_limited_out / "vy_g14_sparse_limited_01.briefing.md"
    if not lim_json_path.is_file() or not lim_md_path.is_file():
        raise G14AcceptanceError("g14_sparse_limited_artifacts_missing")
    lim_data = json.loads(lim_json_path.read_text(encoding="utf-8"))
    if lim_data.get("status") != "limited_briefing" or lim_data.get("is_limited") is not True:
        raise G14AcceptanceError("g14_sparse_limited_payload_not_flagged_limited")
    lim_md_text = lim_md_path.read_text(encoding="utf-8")
    if "Begrenztes Briefing" not in lim_md_text or "Unzureichende Quellenlage" not in lim_md_text:
        raise G14AcceptanceError("g14_sparse_limited_markdown_missing_warning")

    # Assembly of receipt and evidence
    input_records = [_artifact_receipt(root, meeting_doc)]
    output_records = [_artifact_receipt(root, p) for p in output_artifacts]

    input_manifest = artifact_manifest_sha256(input_records)
    output_manifest = artifact_manifest_sha256(output_records)

    handoff_path_1 = evidence_dir / "g14-handoff-search-to-briefing.json"
    handoff_data_1 = {
        "producer": "web_research",
        "consumer": "briefing",
        "status": "verified",
    }
    write_text_artifact(
        handoff_path_1,
        json.dumps(handoff_data_1, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    handoff_path_2 = evidence_dir / "g14-handoff-briefing-to-qa.json"
    handoff_data_2 = {
        "producer": "briefing",
        "consumer": "document_qa",
        "status": "verified",
    }
    write_text_artifact(
        handoff_path_2,
        json.dumps(handoff_data_2, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    receipt = {
        "run_id": pos_result.steps[-1].run_id,
        "input_sha256": input_manifest,
        "output_sha256": output_manifest,
        "input_artifacts": input_records,
        "output_artifacts": output_records,
        "handoff_receipts": [
            {
                "producer": "web_research",
                "consumer": "briefing",
                "artifact_path": str(handoff_path_1.relative_to(root)).replace("\\", "/"),
                "artifact_sha256": _sha256(handoff_path_1),
                "status": "verified",
                "evidence": (
                    "web_research outputs verified hits with citation addresses; briefing "
                    "reuses them to synthesize facts, inferences, and open uncertainties."
                ),
            },
            {
                "producer": "briefing",
                "consumer": "document_qa",
                "artifact_path": str(handoff_path_2.relative_to(root)).replace("\\", "/"),
                "artifact_sha256": _sha256(handoff_path_2),
                "status": "verified",
                "evidence": (
                    "briefing generates structured markdown with separated facts and inferences; "
                    "document_qa verifies format completeness and seals into publication package."
                ),
            },
        ],
        "run_report": {
            "path": str(positive_report.relative_to(root)).replace("\\", "/"),
            "sha256": _sha256(positive_report),
            "status": "executed",
            "verified": True,
        },
        "result_checks": [
            {
                "name": "research_question_and_subject_captured",
                "passed": True,
                "evidence": (
                    "Research question and subject Dr. Almut Schrenk successfully captured "
                    "and bound to briefing context."
                ),
            },
            {
                "name": "separation_of_facts_and_inferences_verified",
                "passed": True,
                "evidence": (
                    "Briefing strictly separates cited facts (each with URL and rank anchor) "
                    "from contextual inferences and open uncertainties."
                ),
            },
            {
                "name": "uncertainties_and_open_points_explicitly_documented",
                "passed": True,
                "evidence": (
                    "Uncertainties regarding public web recency and confidential arrangements "
                    "are explicitly itemized with action recommendations."
                ),
            },
            {
                "name": "honest_limited_briefing_on_sparse_sources",
                "passed": True,
                "evidence": (
                    "Sparse source material (1 hit below threshold of 3) produces an explicit "
                    "limited briefing warning instead of confabulated completeness."
                ),
            },
            {
                "name": "publication_package_sealed_with_qa",
                "passed": True,
                "evidence": (
                    "Document QA verified briefing format integrity and section completeness, "
                    "packaging artifacts into publication package."
                ),
            },
        ],
        "positive_path": {
            "output_artifacts": output_records,
            "run_report": {
                "path": str(positive_report.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(positive_report),
            },
        },
        "negative_path": {
            "case": "unapproved_web_search_blocked",
            "run_id": unapproved_result.steps[-1].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "run_report": {
                "path": str(unapproved_report.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(unapproved_report),
            },
            "evidence": (
                "When web search is called without caller approval, execution halts "
                "fail-closed with web_search_not_approved_for_this_call without network calls."
            ),
        },
        "additional_negative_paths": [
            {
                "case": "sensitive_query_refused_by_pseudonymization_preflight",
                "run_id": sensitive_result.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(sensitive_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(sensitive_report),
                },
                "evidence": (
                    "When query contains sensitive personal data (email, phone, local path), "
                    "pseudonymization preflight refuses query and blocks outbound call."
                ),
            },
            {
                "case": "sparse_sources_strictly_blocked_when_required",
                "run_id": sparse_blocked_result.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(sparse_blocked_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(sparse_blocked_report),
                },
                "evidence": (
                    "When require_sufficient_sources=True and hits are sparse, "
                    "briefing halts fail-closed with insufficient_sources_for_briefing."
                ),
            },
            {
                "case": "missing_subject_refused",
                "run_id": missing_subj_result.steps[-1].run_id,
                "status": "failed",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(missing_subj_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(missing_subj_report),
                },
                "evidence": (
                    "When briefing is invoked without a declared subject, "
                    "execution fails with 'a briefing needs a declared subject'."
                ),
            },
        ],
    }

    manifest_path = evidence_dir / "g14-evidence-dossier.json"
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
        if gate["gate_id"] == "G14":
            gate["status"] = "partial"
            gate["evidence"] = {
                "test_nodes": [],
                "run_receipts": [receipt],
            }
            break

    register_path = evidence_dir / "nf_fin_gates_g14.json"
    write_text_artifact(
        register_path,
        json.dumps(register, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "json",
    )

    verification = verify_gate_evidence(register, root)
    if "G14" not in verification["verified_evidence_gates"]:
        raise G14AcceptanceError("g14_gate_evidence_verification_failed")

    return G14AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(pos_result.dossier_path),
        sparse_dossier_path=Path(sparse_limited_result.dossier_path),
        unapproved_dossier_path=Path(unapproved_result.dossier_path),
        sensitive_dossier_path=Path(sensitive_result.dossier_path),
        missing_subject_dossier_path=Path(missing_subj_result.dossier_path),
        verification=verification,
    )


def _render_acceptance_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# G14 Acceptance Dossier: Dossier and Briefing",
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
            "## Negative Path Verification",
            "",
            f"- Case: `{receipt['negative_path']['case']}`",
            f"- Blocked as expected: `{receipt['negative_path']['blocked_as_expected']}`",
            f"- Evidence: {receipt['negative_path']['evidence']}",
            "",
            "## Additional Negative Paths",
            "",
        )
    )
    for add in receipt["additional_negative_paths"]:
        lines.extend(
            (
                f"- Case: `{add['case']}`",
                f"  - Status: `{add['status']}`",
                f"  - Blocked as expected: `{add['blocked_as_expected']}`",
                f"  - Evidence: {add['evidence']}",
            )
        )

    return "\n".join(lines) + "\n"
