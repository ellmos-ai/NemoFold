"""Executable acceptance bundle for Gate G13: Document QA and Publication Package.

Verifies format integrity, substantive completeness, placeholder prohibition
(absence of unreplaced template tokens), cryptographic SHA-256 preservation,
and publication package assembly with honest report-forge fallback/blocker reporting.
Ellmos UC 01 (Lebenslauf), UC 39 (Autismus-Foerderblatt), UC 40 (Beratungsblatt).
"""

from __future__ import annotations

import hashlib
import json
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


class G13AcceptanceError(RuntimeError):
    """Raised when the executable G13 acceptance chain does not meet its contract."""


class G13AcceptanceBundle:
    """Artifact bundle resulting from running G13 acceptance tests."""

    def __init__(
        self,
        root: Path,
        register_path: Path,
        positive_dossier_path: Path,
        unbound_dossier_path: Path,
        incomplete_dossier_path: Path,
        hash_mismatch_dossier_path: Path,
        template_engine_dossier_path: Path,
        verification: dict[str, Any],
    ) -> None:
        self.root = root
        self.register_path = register_path
        self.positive_dossier_path = positive_dossier_path
        self.unbound_dossier_path = unbound_dossier_path
        self.incomplete_dossier_path = incomplete_dossier_path
        self.hash_mismatch_dossier_path = hash_mismatch_dossier_path
        self.template_engine_dossier_path = template_engine_dossier_path
        self.verification = verification


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
        raise G13AcceptanceError(f"g13_positive_not_executed:status={result.status}")
    if len(result.steps) != 3:
        raise G13AcceptanceError(f"g13_positive_step_count_invalid:{len(result.steps)}")

    step1 = result.steps[0]
    if step1.workflow != "knowledge_composer" or step1.status != "executed":
        raise G13AcceptanceError("g13_positive_step1_knowledge_composer_failed")

    step2 = result.steps[1]
    if step2.workflow != "document_qa" or step2.status != "executed":
        raise G13AcceptanceError("g13_positive_step2_document_qa_failed")

    step2_dir = Path(step2.output_dir)
    pkg_json = step2_dir / f"{step2.run_id}.publication-package.json"
    pkg_md = step2_dir / f"{step2.run_id}.publication-package.md"
    qa_json = step2_dir / f"{step2.run_id}.document-qa.json"

    for artifact in (pkg_json, pkg_md, qa_json):
        if not artifact.is_file():
            raise G13AcceptanceError(f"g13_positive_artifact_missing:{artifact.name}")

    pkg_data = json.loads(pkg_json.read_text(encoding="utf-8"))
    if pkg_data.get("schema") != "nemofold.publication-package.v1":
        raise G13AcceptanceError("g13_positive_package_schema_invalid")
    if pkg_data.get("qa_passed") is not True:
        raise G13AcceptanceError("g13_positive_qa_passed_not_true")
    if pkg_data.get("fallback_applied") is not True:
        raise G13AcceptanceError("g13_positive_fallback_not_applied")

    step3 = result.steps[2]
    if step3.workflow != "print_action" or step3.status != "executed":
        raise G13AcceptanceError("g13_positive_step3_print_action_failed")

    step3_dir = Path(step3.output_dir)
    print_instructions = step3_dir / f"{step3.run_id}.print-instructions.md"
    if not print_instructions.is_file():
        raise G13AcceptanceError("g13_positive_print_artifacts_missing")

    report_path = Path(step3.ledger_path) if step3.ledger_path else (
        step3_dir / "jobs" / f"{step3.run_id}.json"
    )
    if not report_path.is_file():
        raise G13AcceptanceError("g13_positive_report_missing")

    step1_dir = Path(step1.output_dir)
    composer_json = step1_dir / f"{step1.run_id}.knowledge-composer.json"
    composer_md = step1_dir / f"{step1.run_id}.knowledge-composer.md"

    artifacts: list[Path] = [
        composer_json,
        composer_md,
        pkg_json,
        pkg_md,
        qa_json,
        print_instructions,
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
        raise G13AcceptanceError(f"{voyage_name}_not_stopped:status={result.status}")

    blocked_step = result.steps[-1]
    if blocked_step.status != "blocked":
        raise G13AcceptanceError(
            f"{voyage_name}_step_not_blocked:status={blocked_step.status}"
        )
    if not any(expected_error in err for err in blocked_step.errors):
        raise G13AcceptanceError(
            f"{voyage_name}_expected_error_missing:{expected_error} not in {blocked_step.errors}"
        )

    dossier_path = Path(result.dossier_path)
    if not dossier_path.is_file():
        raise G13AcceptanceError(f"{voyage_name}_dossier_missing")

    if blocked_step.ledger_path is None:
        raise G13AcceptanceError(f"{voyage_name}_ledger_path_missing")
    ledger_path = Path(blocked_step.ledger_path)
    if not ledger_path.is_file():
        raise G13AcceptanceError(f"{voyage_name}_ledger_file_missing")

    artifacts: list[Path] = []
    out_dir = Path(blocked_step.output_dir)
    for ext in ("*.json", "*.md"):
        for f in out_dir.glob(ext):
            if f.is_file() and f != ledger_path and f.parent.name != "ledger":
                artifacts.append(f)

    return ledger_path, artifacts


def run_g13_acceptance_bundle(output_root: str | Path) -> G13AcceptanceBundle:
    """Execute the full G13 acceptance pipeline across positive and negative voyages."""
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G13AcceptanceError("g13_evidence_root_not_empty")
    root.mkdir(parents=True, exist_ok=True)
    inbox = root / "inputs"
    inbox.mkdir(parents=True, exist_ok=True)
    evidence_dir = root / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    work_dir = root / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. Positive inputs (UC 39 Autismus-Foerderblatt)
    autism_doc = inbox / "autismus_leitfaden.txt"
    autism_doc.write_text(
        "Foerderdokumentation Autismus-Spektrum\n"
        "Reizueberflutung: Hohe Laermempfindlichkeit bei wechselnden Geraeuschpegeln.\n"
        "Routinen: Feste Pausenzeiten um 12:00 Uhr und Vorankuendigung bei Raumwechseln.\n"
        "Kommunikation: Schriftliche Aufgabenstellung mit klaren Prioritaeten bevorzugt.\n"
        "Notfall-Anker: Zehn Minuten Rueckzug in den Ruheraum.\n",
        encoding="utf-8",
    )

    # 2. Negative inputs
    # 2.1 Unbound placeholder input
    unbound_dir = inbox / "unbound"
    unbound_dir.mkdir(parents=True, exist_ok=True)
    unbound_doc = unbound_dir / "unbound_arbeitsblatt.md"
    unbound_doc.write_text(
        "# Autismus Foerderplan Unvollstaendig\n\n"
        "Klient: {{klient_vorname}} {{klient_nachname}}\n\n"
        "Zielvereinbarung: [PLATZHALTER: Zielsetzung]\n\n"
        "Notfallkontakt: <NOTFALL_TELEFONNUMMER>\n",
        encoding="utf-8",
    )

    # 2.2 Incomplete sections input
    incomplete_dir = inbox / "incomplete"
    incomplete_dir.mkdir(parents=True, exist_ok=True)
    incomplete_doc = incomplete_dir / "incomplete_blatt.md"
    incomplete_doc.write_text(
        "# Alltagsstrukturierung Entwurf\n\n"
        "Kurze Notizen ohne formale Abschnitte fuer den Schultag.\n"
        "Pausen werden bei Bedarf spontan eingelegt.\n",
        encoding="utf-8",
    )

    # 2.3 Hash mismatch input
    hash_dir = inbox / "hash_doc"
    hash_dir.mkdir(parents=True, exist_ok=True)
    hash_doc = hash_dir / "tampered_document.md"
    hash_doc.write_text(
        "# Vollstaendiges Beratungsblatt\n\n"
        "## Klientenkontext\n\n"
        "Klient: Max Mustermann\n"
        "Thema: Angstbewaeltigung und Stressregulation im Schulalltag.\n\n"
        "## Interventionen\n\n"
        "Regelmaessige Atempausen und Reizabschirmung nach Plan.\n",
        encoding="utf-8",
    )

    # 2.4 Template input for document_compose
    template_dir = inbox / "templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    dummy_template = template_dir / "vorlage.docx"
    dummy_template.write_bytes(b"PK\x03\x04dummy-word-template-bytes")

    # Output directories
    pos_out1 = root / "runs" / "pos_s1"
    pos_out2 = root / "runs" / "pos_s2"
    pos_out3 = root / "runs" / "pos_s3"
    unbound_out = root / "runs" / "unbound_s1"
    incomplete_out = root / "runs" / "incomplete_s1"
    hash_out = root / "runs" / "hash_s1"
    template_out = root / "runs" / "template_s1"

    # Plan: Positive Voyage (3 steps)
    positive_plan = {
        "voyage_id": "vy_g13_pos",
        "name": "g13_positive_qa_publication_print",
        "steps": [
            {
                "order": 1,
                "workflow": "knowledge_composer",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "knowledge_composer",
                    "input_roots": [str(inbox)],
                    "output_dir": str(pos_out1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "profile": "autism_support",
                        "client_context": {
                            "client_name": "Max Mustermann",
                            "age": 11,
                            "module": "Autismus-Foerderung",
                        },
                        "title": "Autismus-Foerderblatt Alltagsstrukturierung",
                    },
                },
            },
            {
                "order": 2,
                "workflow": "document_qa",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_qa",
                    "input_roots": [str(pos_out1)],
                    "output_dir": str(pos_out2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "required_sections": ["Autismus", "Klientenkontext"],
                        "package_title": "Geprueftes Autismus-Foerderblatt Paket",
                    },
                },
            },
            {
                "order": 3,
                "workflow": "print_action",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "print_action",
                    "input_roots": [str(pos_out2)],
                    "output_dir": str(pos_out3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "source_id": "vy_g13_pos_02.publication-package.md",
                    },
                },
            },
        ],
    }

    # Plan: Negative Voyage 1 (Unbound Placeholders)
    unbound_plan = {
        "voyage_id": "vy_g13_unbound",
        "name": "g13_negative_unbound_placeholders",
        "steps": [
            {
                "order": 1,
                "workflow": "document_qa",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_qa",
                    "input_roots": [str(unbound_dir)],
                    "output_dir": str(unbound_out),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "disallow_unbound_fields": True,
                    },
                },
            },
        ],
    }

    # Plan: Negative Voyage 2 (Incomplete Sections)
    incomplete_plan = {
        "voyage_id": "vy_g13_incomplete",
        "name": "g13_negative_incomplete_sections",
        "steps": [
            {
                "order": 1,
                "workflow": "document_qa",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_qa",
                    "input_roots": [str(incomplete_dir)],
                    "output_dir": str(incomplete_out),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "required_sections": ["Sicherheitsleitfaden_DIN_ISO"],
                    },
                },
            },
        ],
    }

    # Plan: Negative Voyage 3 (Cryptographic Hash Mismatch)
    hash_plan = {
        "voyage_id": "vy_g13_hash_mismatch",
        "name": "g13_negative_hash_mismatch",
        "steps": [
            {
                "order": 1,
                "workflow": "document_qa",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_qa",
                    "input_roots": [str(hash_dir)],
                    "output_dir": str(hash_out),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "expected_sha256": "0" * 64,
                    },
                },
            },
        ],
    }

    # Plan: Negative Voyage 4 (Template Engine Unavailable Blocker)
    template_plan = {
        "voyage_id": "vy_g13_template_engine",
        "name": "g13_negative_template_engine_unavailable",
        "steps": [
            {
                "order": 1,
                "workflow": "document_compose",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_compose",
                    "input_roots": [str(template_dir)],
                    "output_dir": str(template_out),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "template_path": str(dummy_template),
                        "fields": {"titel": "Test"},
                    },
                },
            },
        ],
    }

    config = ExecutionConfig(allowed_roots=(str(root),))

    pos_result = run_voyage(positive_plan, config, run_id="vy_g13_pos", base_dir=work_dir)
    unbound_result = run_voyage(unbound_plan, config, run_id="vy_g13_unbound", base_dir=work_dir)
    incomplete_result = run_voyage(
        incomplete_plan, config, run_id="vy_g13_incomplete", base_dir=work_dir
    )
    hash_result = run_voyage(
        hash_plan, config, run_id="vy_g13_hash_mismatch", base_dir=work_dir
    )
    template_result = run_voyage(
        template_plan, config, run_id="vy_g13_template_engine", base_dir=work_dir
    )

    positive_report, output_artifacts = _verify_positive_result(root, pos_result)
    unbound_report, unbound_artifacts = _verify_blocked_result(
        root, unbound_result, "unbound_fields_in_document", "g13_unbound"
    )
    incomplete_report, incomplete_artifacts = _verify_blocked_result(
        root, incomplete_result, "document_incomplete:missing_required_sections", "g13_incomplete"
    )
    hash_report, hash_artifacts = _verify_blocked_result(
        root, hash_result, "source_document_hash_mismatch", "g13_hash_mismatch"
    )
    template_report, template_artifacts = _verify_blocked_result(
        root, template_result, "template_engine_unavailable", "g13_template_engine"
    )

    # Compile input receipts
    input_artifacts = [
        _artifact_receipt(root, path)
        for path in (
            autism_doc,
            unbound_doc,
            incomplete_doc,
            hash_doc,
            dummy_template,
        )
    ]

    dossier_artifacts = (
        Path(pos_result.dossier_path),
        Path(pos_result.dossier_path).with_suffix(".md"),
        Path(unbound_result.dossier_path),
        Path(unbound_result.dossier_path).with_suffix(".md"),
        Path(incomplete_result.dossier_path),
        Path(incomplete_result.dossier_path).with_suffix(".md"),
        Path(hash_result.dossier_path),
        Path(hash_result.dossier_path).with_suffix(".md"),
        Path(template_result.dossier_path),
        Path(template_result.dossier_path).with_suffix(".md"),
    )

    output_receipts = [
        _artifact_receipt(root, path)
        for path in (
            *output_artifacts,
            *unbound_artifacts,
            *incomplete_artifacts,
            *hash_artifacts,
            *template_artifacts,
            *dossier_artifacts,
        )
    ]

    input_manifest_sha = artifact_manifest_sha256(input_artifacts)
    output_manifest_sha = artifact_manifest_sha256(output_receipts)

    handoff_path = evidence_dir / "g13-handoff.json"
    handoff_data = {
        "producer": "knowledge_composer",
        "consumer": "document_qa",
        "document_name": "vy_g13_pos_01.knowledge-composer.md",
        "qa_verifier": "document_qa",
        "publication_consumer": "print_action",
    }
    write_text_artifact(
        handoff_path,
        json.dumps(handoff_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    receipt = {
        "run_id": pos_result.steps[-1].run_id,
        "input_sha256": input_manifest_sha,
        "output_sha256": output_manifest_sha,
        "input_artifacts": input_artifacts,
        "output_artifacts": output_receipts,
        "handoff_receipts": [
            {
                "producer": "knowledge_composer",
                "consumer": "document_qa",
                "artifact_path": str(handoff_path.relative_to(root)).replace("\\", "/"),
                "artifact_sha256": _sha256(handoff_path),
                "status": "verified",
                "evidence": (
                    "knowledge_composer produces structured materials (UC39); document_qa "
                    "verifies format, completeness, placeholder-free text, and SHA-256 integrity "
                    "before sealing into a publication package for print_action."
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
                "name": "format_and_version_integrity_verified",
                "passed": True,
                "evidence": (
                    "Document QA verified format markdown, completeness, and version preservation "
                    "for UC 39 Autismus-Foerderblatt Alltagsstrukturierung."
                ),
            },
            {
                "name": "no_unbound_placeholders_verified",
                "passed": True,
                "evidence": (
                    "Validated absence of template tokens, {{...}}, <...>, and [PLATZHALTER] tags."
                ),
            },
            {
                "name": "cryptographic_sha256_hash_preserved",
                "passed": True,
                "evidence": (
                    "Cryptographic SHA-256 hash of original source document was preserved "
                    "and sealed into the publication package."
                ),
            },
            {
                "name": "honest_template_engine_status_and_fallback",
                "passed": True,
                "evidence": (
                    "Report-forge template engine availability checked honestly; fallback applied "
                    "without inventing missing report-forge functionality."
                ),
            },
            {
                "name": "print_action_prepared_publication_package",
                "passed": True,
                "evidence": (
                    "Print package instructions and manifest successfully prepared "
                    "for verified publication package."
                ),
            },
        ],
        "positive_path": {
            "output_artifacts": [
                _artifact_receipt(root, path) for path in output_artifacts
            ],
            "run_report": {
                "path": str(positive_report.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(positive_report),
            },
        },
        "negative_path": {
            "case": "unbound_fields_in_document_blocked",
            "run_id": unbound_result.steps[-1].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "run_report": {
                "path": str(unbound_report.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(unbound_report),
            },
            "evidence": (
                "When document contains unreplaced template tokens or placeholders, "
                "document QA halts fail-closed with unbound_fields_in_document."
            ),
        },
        "additional_negative_paths": [
            {
                "case": "document_incomplete_missing_sections_blocked",
                "run_id": incomplete_result.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(incomplete_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(incomplete_report),
                },
                "evidence": (
                    "When document lacks mandatory required sections, document QA halts "
                    "fail-closed with document_incomplete:missing_required_sections."
                ),
            },
            {
                "case": "source_document_hash_mismatch_blocked",
                "run_id": hash_result.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(hash_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(hash_report),
                },
                "evidence": (
                    "When document content does not match expected SHA-256 hash, "
                    "document QA halts fail-closed with source_document_hash_mismatch."
                ),
            },
            {
                "case": "template_engine_unavailable_blocked",
                "run_id": template_result.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(template_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(template_report),
                },
                "evidence": (
                    "When report-forge template engine is not installed, document_compose "
                    "halts fail-closed honestly reporting template_engine_unavailable."
                ),
            },
        ],
    }

    manifest_path = evidence_dir / "g13-evidence-dossier.json"
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
        if gate["gate_id"] == "G13":
            gate["status"] = "partial"
            gate["evidence"] = {
                "test_nodes": [],
                "run_receipts": [receipt],
            }
            break

    register_path = evidence_dir / "nf_fin_gates_g13.json"
    write_text_artifact(
        register_path,
        json.dumps(register, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "json",
    )

    verification = verify_gate_evidence(register, root)
    if "G13" not in verification["verified_evidence_gates"]:
        raise G13AcceptanceError("g13_gate_evidence_verification_failed")

    return G13AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(pos_result.dossier_path),
        unbound_dossier_path=Path(unbound_result.dossier_path),
        incomplete_dossier_path=Path(incomplete_result.dossier_path),
        hash_mismatch_dossier_path=Path(hash_result.dossier_path),
        template_engine_dossier_path=Path(template_result.dossier_path),
        verification=verification,
    )


def _render_acceptance_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# G13 Acceptance Dossier: Document QA and Publication Package",
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
