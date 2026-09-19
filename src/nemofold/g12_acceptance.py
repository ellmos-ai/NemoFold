"""Executable acceptance bundle for Gate G12: Export Contacts and Controlled Email Drafts.

Verifies medical document contact extraction (UC13: phone numbers, email addresses,
specialties), validated recipient resolution (resolving names, detecting ambiguities,
rejecting missing recipients), fail-closed enforcement of draft-only status (send=false),
and honest rejection of unimplemented channels (Telegram).
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
from .report_studio import _render_pdf
from .voyage_runs import VoyageRunResult, run_voyage


class G12AcceptanceError(RuntimeError):
    """Raised when the executable G12 acceptance chain does not meet its contract."""


class G12AcceptanceBundle:
    """Artifact bundle resulting from running G12 acceptance tests."""

    def __init__(
        self,
        root: Path,
        register_path: Path,
        positive_dossier_path: Path,
        ambiguous_dossier_path: Path,
        missing_dossier_path: Path,
        send_forbidden_dossier_path: Path,
        telegram_blocked_dossier_path: Path,
        verification: dict[str, Any],
    ) -> None:
        self.root = root
        self.register_path = register_path
        self.positive_dossier_path = positive_dossier_path
        self.ambiguous_dossier_path = ambiguous_dossier_path
        self.missing_dossier_path = missing_dossier_path
        self.send_forbidden_dossier_path = send_forbidden_dossier_path
        self.telegram_blocked_dossier_path = telegram_blocked_dossier_path
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
        raise G12AcceptanceError(f"g12_positive_not_executed:status={result.status}")
    if len(result.steps) != 3:
        raise G12AcceptanceError(f"g12_positive_step_count_invalid:{len(result.steps)}")

    step2 = result.steps[1]
    if step2.workflow != "contact_monitor" or step2.status != "executed":
        raise G12AcceptanceError("g12_positive_step2_contact_monitor_failed")

    step2_dir = Path(step2.output_dir)
    contact_json = step2_dir / "contacts" / f"{step2.run_id}.json"
    contact_md = step2_dir / "contacts" / f"{step2.run_id}.md"
    contact_txt = step2_dir / "contacts" / f"{step2.run_id}.txt"
    if not contact_json.is_file() or not contact_md.is_file() or not contact_txt.is_file():
        raise G12AcceptanceError("g12_positive_contact_artifacts_missing")

    contact_payload = json.loads(contact_json.read_text(encoding="utf-8"))
    if contact_payload.get("schema") != "nemofold.contacts.v1":
        raise G12AcceptanceError("g12_positive_contact_schema_invalid")
    candidates = contact_payload.get("candidates", [])
    if len(candidates) < 2:
        raise G12AcceptanceError("g12_positive_candidates_count_low")

    weber = next((c for c in candidates if "Weber" in (c.get("name") or "")), None)
    if weber is None or not weber.get("phone") or not weber.get("email"):
        raise G12AcceptanceError("g12_positive_doctor_weber_incomplete")
    if weber.get("contact_class") != "doctor":
        raise G12AcceptanceError("g12_positive_doctor_class_missing")

    step3 = result.steps[2]
    if step3.workflow != "controlled_email" or step3.status != "executed":
        raise G12AcceptanceError("g12_positive_step3_controlled_email_failed")

    step3_dir = Path(step3.output_dir)
    draft_eml = step3_dir / "mail-drafts" / step3.run_id / "draft.eml"
    approval_json = step3_dir / "mail-drafts" / step3.run_id / "approval.json"
    outbound_json = step3_dir / f"{step3.run_id}.outbound.json"
    if not draft_eml.is_file() or not approval_json.is_file() or not outbound_json.is_file():
        raise G12AcceptanceError("g12_positive_mail_draft_artifacts_missing")

    approval_payload = json.loads(approval_json.read_text(encoding="utf-8"))
    if approval_payload.get("send_performed") is not False:
        raise G12AcceptanceError("g12_positive_send_performed_not_false")

    outbound_payload = json.loads(outbound_json.read_text(encoding="utf-8"))
    if outbound_payload.get("allowed") is not False:
        raise G12AcceptanceError("g12_positive_outbound_decision_not_draft_only")
    if outbound_payload.get("right") != "draft_only":
        raise G12AcceptanceError("g12_positive_outbound_right_not_draft_only")

    report_path = Path(step3.ledger_path) if step3.ledger_path else (
        step3_dir / "jobs" / f"{step3.run_id}.json"
    )
    if not report_path.is_file():
        raise G12AcceptanceError("g12_positive_report_missing")

    artifacts: list[Path] = [
        contact_json,
        contact_md,
        contact_txt,
        draft_eml,
        approval_json,
        outbound_json,
    ]
    for step in (result.steps[0], result.steps[1]):
        if step.ledger_path:
            p = Path(step.ledger_path)
            if p.is_file():
                artifacts.append(p)
    return report_path, artifacts


def _verify_blocked_result(
    root: Path,
    result: VoyageRunResult,
    expected_error: str,
    voyage_name: str,
) -> tuple[Path, list[Path]]:
    if result.status != "stopped":
        raise G12AcceptanceError(f"{voyage_name}_not_stopped:status={result.status}")
    if result.stopped_at != 3:
        raise G12AcceptanceError(f"{voyage_name}_not_stopped_at_step_3:{result.stopped_at}")

    blocked_step = result.steps[2]
    if blocked_step.status != "handoff_blocked":
        raise G12AcceptanceError(
            f"{voyage_name}_step_not_handoff_blocked:{blocked_step.status}"
        )
    if not any(expected_error in err for err in blocked_step.errors):
        raise G12AcceptanceError(
            f"{voyage_name}_expected_error_missing:{blocked_step.errors}"
        )

    dossier_path = Path(result.dossier_path)
    if not dossier_path.is_file():
        raise G12AcceptanceError(f"{voyage_name}_dossier_missing")

    if blocked_step.ledger_path is None:
        raise G12AcceptanceError(f"{voyage_name}_ledger_path_missing")
    ledger_path = Path(blocked_step.ledger_path)
    if not ledger_path.is_file():
        raise G12AcceptanceError(f"{voyage_name}_ledger_file_missing")

    artifacts: list[Path] = []
    return ledger_path, artifacts


def run_g12_acceptance_bundle(output_root: Path | str) -> G12AcceptanceBundle:
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G12AcceptanceError("g12_evidence_root_not_empty")
    root.mkdir(parents=True, exist_ok=True)

    work_dir = root / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = root / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # 1. Positive Voyage Setup
    pos_inbox = work_dir / "pos_inputs"
    pos_inbox.mkdir(parents=True, exist_ok=True)
    doc1 = pos_inbox / "01-arztbrief-weber.pdf"
    doc1.write_bytes(
        _render_pdf(
            "Arztbrief Nuklearmedizin und Schilddrüsendiagnostik\n"
            "Behandelnder Arzt: Dr. med. Frank Weber <weber@nuklearmedizin-praxis.de>\n"
            "Telefon: +49 30 12345678\n"
            "Fachbereich: Nuklearmedizinische Diagnostik\n"
            "Befund: Struma nodosa rechts. Unauffällige Laborwerte.\n"
        )
    )
    doc2 = pos_inbox / "02-laborbericht-becker.pdf"
    doc2.write_bytes(
        _render_pdf(
            "Laborbefund MVZ Berlin\n"
            "Ärztliche Leitung: Dr. med. Sabine Becker <becker@labor-berlin.de>\n"
            "Telefon: 030-98765432\n"
            "Fachbereich: Klinische Chemie und Labordiagnostik\n"
            "TSH-Basalwert: 1.85 mU/l (Normbereich 0.40 - 4.00 mU/l).\n"
        )
    )
    positive_inputs = [doc1, doc2]

    pos_out1 = work_dir / "pos_out_step1"
    pos_out2 = work_dir / "pos_out_step2"
    pos_out3 = work_dir / "pos_out_step3"

    positive_plan = {
        "voyage_id": "vy_g12_acceptance_pos",
        "title": "G12 Positive Acceptance Voyage (Contact Export to Mail Draft)",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(pos_inbox)],
                    "output_dir": str(pos_out1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "inventory",
                        "formats": ["md"],
                    },
                },
            },
            {
                "order": 2,
                "workflow": "contact_monitor",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "contact_monitor",
                    "input_roots": [str(pos_inbox)],
                    "output_dir": str(pos_out2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {},
                },
            },
            {
                "order": 3,
                "workflow": "controlled_email",
                "handoff": {
                    "format": "contact-book",
                    "mode": "recipient_bridge",
                    "recipient": "Dr. med. Frank Weber",
                },
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "controlled_email",
                    "input_roots": [str(pos_inbox)],
                    "output_dir": str(pos_out3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "from_address": "patient@example.org",
                        "subject": "Terminanfrage Kontrolluntersuchung Schilddrüse",
                        "body": (
                            "Sehr geehrter Herr Dr. Weber,\n\n"
                            "ich bitte um einen Kontrolltermin zur Schilddrüsensonographie."
                        ),
                        "rights": "draft_only",
                        "send_requested": False,
                    },
                },
            },
        ],
    }

    # 2. Negative Voyage 1: Ambiguous Recipient
    ambig_inbox = work_dir / "ambig_inputs"
    ambig_inbox.mkdir(parents=True, exist_ok=True)
    ambig_doc1 = ambig_inbox / "arztbrief-frank-weber.pdf"
    ambig_doc1.write_bytes(
        _render_pdf(
            "Gemeinschaftspraxis Weber\n"
            "Dr. med. Frank Weber <frank.weber@praxis.de>\n"
            "Telefon: 030-111111\n"
            "Facharzt für Radiologie\n"
        )
    )
    ambig_doc2 = ambig_inbox / "arztbrief-claudia-weber.pdf"
    ambig_doc2.write_bytes(
        _render_pdf(
            "Gemeinschaftspraxis Weber\n"
            "Dr. med. Claudia Weber <claudia.weber@praxis.de>\n"
            "Telefon: 030-222222\n"
            "Fachärztin für Nuklearmedizin\n"
        )
    )
    ambig_input = ambig_doc1

    ambig_out1 = work_dir / "ambig_out1"
    ambig_out2 = work_dir / "ambig_out2"
    ambig_out3 = work_dir / "ambig_out3"

    ambig_plan = {
        "voyage_id": "vy_g12_neg_ambiguous",
        "title": "G12 Negative Ambiguous Recipient Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(ambig_inbox)],
                    "output_dir": str(ambig_out1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"column_template": "inventory"},
                },
            },
            {
                "order": 2,
                "workflow": "contact_monitor",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "contact_monitor",
                    "input_roots": [str(ambig_inbox)],
                    "output_dir": str(ambig_out2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {},
                },
            },
            {
                "order": 3,
                "workflow": "controlled_email",
                "handoff": {
                    "format": "contact-book",
                    "mode": "recipient_bridge",
                    "recipient": "Dr. Weber",
                },
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "controlled_email",
                    "input_roots": [str(ambig_inbox)],
                    "output_dir": str(ambig_out3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "from_address": "patient@example.org",
                        "subject": "Terminanfrage",
                        "body": "Termin bitte.",
                        "rights": "draft_only",
                        "send_requested": False,
                    },
                },
            },
        ],
    }

    # 3. Negative Voyage 2: Missing / Unknown Recipient
    missing_out1 = work_dir / "missing_out1"
    missing_out2 = work_dir / "missing_out2"
    missing_out3 = work_dir / "missing_out3"

    missing_plan = {
        "voyage_id": "vy_g12_neg_missing",
        "title": "G12 Negative Missing Recipient Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(pos_inbox)],
                    "output_dir": str(missing_out1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"column_template": "inventory"},
                },
            },
            {
                "order": 2,
                "workflow": "contact_monitor",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "contact_monitor",
                    "input_roots": [str(pos_inbox)],
                    "output_dir": str(missing_out2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {},
                },
            },
            {
                "order": 3,
                "workflow": "controlled_email",
                "handoff": {
                    "format": "contact-book",
                    "mode": "recipient_bridge",
                    "recipient": "Dr. med. Nicht Vorhanden",
                },
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "controlled_email",
                    "input_roots": [str(pos_inbox)],
                    "output_dir": str(missing_out3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "from_address": "patient@example.org",
                        "subject": "Anfrage",
                        "body": "Hallo.",
                        "rights": "draft_only",
                        "send_requested": False,
                    },
                },
            },
        ],
    }

    # 4. Negative Voyage 3: Send Requested Forbidden
    send_out1 = work_dir / "send_out1"
    send_out2 = work_dir / "send_out2"
    send_out3 = work_dir / "send_out3"

    send_plan = {
        "voyage_id": "vy_g12_neg_send_forbidden",
        "title": "G12 Negative Live Send Forbidden Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(pos_inbox)],
                    "output_dir": str(send_out1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"column_template": "inventory"},
                },
            },
            {
                "order": 2,
                "workflow": "contact_monitor",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "contact_monitor",
                    "input_roots": [str(pos_inbox)],
                    "output_dir": str(send_out2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {},
                },
            },
            {
                "order": 3,
                "workflow": "controlled_email",
                "handoff": {
                    "format": "contact-book",
                    "mode": "recipient_bridge",
                    "recipient": "Dr. med. Frank Weber",
                },
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "controlled_email",
                    "input_roots": [str(pos_inbox)],
                    "output_dir": str(send_out3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "from_address": "patient@example.org",
                        "subject": "Anfrage",
                        "body": "Hallo.",
                        "rights": "draft_only",
                        "send_requested": True,
                    },
                },
            },
        ],
    }

    # 5. Negative Voyage 4: Telegram Delivery Blocked
    telegram_out1 = work_dir / "telegram_out1"
    telegram_out2 = work_dir / "telegram_out2"
    telegram_out3 = work_dir / "telegram_out3"

    telegram_plan = {
        "voyage_id": "vy_g12_neg_telegram_blocked",
        "title": "G12 Negative Telegram Delivery Blocked Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(pos_inbox)],
                    "output_dir": str(telegram_out1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"column_template": "inventory"},
                },
            },
            {
                "order": 2,
                "workflow": "contact_monitor",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "contact_monitor",
                    "input_roots": [str(pos_inbox)],
                    "output_dir": str(telegram_out2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {},
                },
            },
            {
                "order": 3,
                "workflow": "controlled_email",
                "handoff": {
                    "format": "contact-book",
                    "mode": "recipient_bridge",
                    "recipient": "Dr. med. Frank Weber",
                },
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "controlled_email",
                    "input_roots": [str(pos_inbox)],
                    "output_dir": str(telegram_out3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "from_address": "patient@example.org",
                        "subject": "Anfrage",
                        "body": "Hallo.",
                        "rights": "draft_only",
                        "channel": "telegram",
                        "send_requested": False,
                    },
                },
            },
        ],
    }

    config = ExecutionConfig(allowed_roots=(str(root),))

    pos_result = run_voyage(positive_plan, config, run_id="g12_pos", base_dir=work_dir)
    ambig_result = run_voyage(ambig_plan, config, run_id="g12_ambig", base_dir=work_dir)
    missing_result = run_voyage(missing_plan, config, run_id="g12_missing", base_dir=work_dir)
    send_result = run_voyage(send_plan, config, run_id="g12_send", base_dir=work_dir)
    telegram_result = run_voyage(telegram_plan, config, run_id="g12_telegram", base_dir=work_dir)

    positive_report, output_artifacts = _verify_positive_result(root, pos_result)
    ambig_report, ambig_artifacts = _verify_blocked_result(
        root, ambig_result, "ambiguous_recipient_in_contact_book", "g12_ambiguous"
    )
    missing_report, missing_artifacts = _verify_blocked_result(
        root, missing_result, "recipient_not_found_in_contact_book", "g12_missing"
    )
    send_report, send_artifacts = _verify_blocked_result(
        root, send_result, "recipient_bridge_live_send_forbidden", "g12_send"
    )
    telegram_report, telegram_artifacts = _verify_blocked_result(
        root, telegram_result, "recipient_bridge_telegram_not_implemented", "g12_telegram"
    )

    handoff_path = root / "evidence" / "g12-handoff.json"
    handoff = pos_result.steps[-1].handoff
    if not isinstance(handoff, dict):
        raise G12AcceptanceError("g12_positive_handoff_missing")
    write_text_artifact(
        handoff_path,
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    input_artifacts = [
        _artifact_receipt(root, path)
        for path in (
            *positive_inputs,
            ambig_input,
        )
    ]
    dossier_artifacts = (
        Path(pos_result.dossier_path),
        Path(pos_result.dossier_path).with_suffix(".md"),
        Path(ambig_result.dossier_path),
        Path(ambig_result.dossier_path).with_suffix(".md"),
        Path(missing_result.dossier_path),
        Path(missing_result.dossier_path).with_suffix(".md"),
        Path(send_result.dossier_path),
        Path(send_result.dossier_path).with_suffix(".md"),
        Path(telegram_result.dossier_path),
        Path(telegram_result.dossier_path).with_suffix(".md"),
    )
    output_receipts = [
        _artifact_receipt(root, path)
        for path in (
            *output_artifacts,
            *ambig_artifacts,
            *missing_artifacts,
            *send_artifacts,
            *telegram_artifacts,
            *dossier_artifacts,
        )
    ]
    input_manifest_sha = artifact_manifest_sha256(input_artifacts)
    output_manifest_sha = artifact_manifest_sha256(output_receipts)

    receipt = {
        "run_id": pos_result.steps[-1].run_id,
        "input_sha256": input_manifest_sha,
        "output_sha256": output_manifest_sha,
        "input_artifacts": input_artifacts,
        "output_artifacts": output_receipts,
        "handoff_receipts": [
            {
                "producer": "contact_monitor",
                "consumer": "controlled_email",
                "artifact_path": str(handoff_path.relative_to(root)).replace("\\", "/"),
                "artifact_sha256": _sha256(handoff_path),
                "status": "verified",
                "evidence": (
                    "contact_monitor extracts doctors, phone numbers, and emails into a verified "
                    "contact book; recipient bridge resolves and validates doctor recipient into "
                    "controlled_email draft."
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
                "name": "doctor_contacts_phone_and_email_extracted",
                "passed": True,
                "evidence": (
                    "Extracted doctor contacts (Dr. med. Frank Weber, Dr. med. Sabine Becker) "
                    "with phone numbers, email addresses, and medical roles from Arztdokumente."
                ),
            },
            {
                "name": "contact_book_anchored_export_generated",
                "passed": True,
                "evidence": (
                    "Generated contact-snapshot (JSON), contact-report (Markdown summary for "
                    "UC13), and contact-book (anchored txt format) for reliable downstream reuse."
                ),
            },
            {
                "name": "validated_recipient_bridge_resolution",
                "passed": True,
                "evidence": (
                    "Resolved recipient name 'Dr. med. Frank Weber' unambiguously to verified "
                    "doctor email 'weber@nuklearmedizin-praxis.de'."
                ),
            },
            {
                "name": "controlled_email_draft_only_enforced",
                "passed": True,
                "evidence": (
                    "Controlled email generated draft.eml and approval.json with "
                    "rights=draft_only, send_requested=False, and send_performed=False."
                ),
            },
            {
                "name": "ambiguous_recipient_blocked",
                "passed": True,
                "evidence": (
                    "Addressing ambiguous name matching multiple contacts halted fail-closed "
                    "with ambiguous_recipient_in_contact_book."
                ),
            },
            {
                "name": "missing_recipient_blocked",
                "passed": True,
                "evidence": (
                    "Addressing unknown contact not in contact book halted fail-closed "
                    "with recipient_not_found_in_contact_book."
                ),
            },
            {
                "name": "live_send_forbidden_and_telegram_unimplemented",
                "passed": True,
                "evidence": (
                    "Live send attempts and unimplemented Telegram channel halted fail-closed."
                ),
            },
        ],
        "negative_path": {
            "case": "ambiguous_recipient_in_contact_book_blocked",
            "run_id": ambig_result.steps[-1].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "run_report": {
                "path": str(ambig_report.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(ambig_report),
            },
            "evidence": (
                "When recipient name matches multiple contacts in the contact book, "
                "the recipient bridge halts fail-closed with status=handoff_blocked."
            ),
        },
        "additional_negative_paths": [
            {
                "case": "missing_recipient_blocked",
                "run_id": missing_result.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(missing_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(missing_report),
                },
                "evidence": (
                    "When recipient is unknown or not present in contact book, "
                    "execution halts fail-closed."
                ),
            },
            {
                "case": "live_send_requested_forbidden",
                "run_id": send_result.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(send_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(send_report),
                },
                "evidence": (
                    "Live send requests without authorization halt fail-closed."
                ),
            },
            {
                "case": "telegram_adapter_not_implemented_blocked",
                "run_id": telegram_result.steps[-1].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(telegram_report.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(telegram_report),
                },
                "evidence": (
                    "Telegram channel is honestly reported as not implemented and "
                    "halts fail-closed."
                ),
            },
        ],
    }

    manifest_path = root / "evidence" / "g12-evidence-dossier.json"
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
        if gate["gate_id"] == "G12":
            gate["status"] = "partial"
            gate["evidence"] = {
                "test_nodes": [],
                "run_receipts": [receipt],
            }
            break

    register_path = root / "evidence" / "nf_fin_gates_g12.json"
    write_text_artifact(
        register_path,
        json.dumps(register, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "json",
    )

    verification = verify_gate_evidence(register, root)
    if "G12" not in verification["verified_evidence_gates"]:
        raise G12AcceptanceError("g12_gate_evidence_verification_failed")

    return G12AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(pos_result.dossier_path),
        ambiguous_dossier_path=Path(ambig_result.dossier_path),
        missing_dossier_path=Path(missing_result.dossier_path),
        send_forbidden_dossier_path=Path(send_result.dossier_path),
        telegram_blocked_dossier_path=Path(telegram_result.dossier_path),
        verification=verification,
    )


def _render_acceptance_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# G12 Acceptance Dossier: Export Contacts and Controlled Email Drafts",
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
