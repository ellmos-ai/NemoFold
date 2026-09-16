"""Tests for Gate G12: Export Contacts and Controlled Email Drafts (Ellmos UC 13).

Verifies phone and email extraction from doctor documents, validated recipient bridge
resolution, and fail-closed draft-only gating.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig
from nemofold.contact_monitor import build_contact_monitor
from nemofold.contracts import SourceRecord
from nemofold.recipient_bridge import (
    RecipientBridgeError,
    validate_recipient_bridge,
)
from nemofold.report_studio import _render_pdf
from nemofold.structured_sources import read_contacts
from nemofold.voyage_runs import run_voyage


def test_contact_monitor_extracts_phone_and_doctor_class(tmp_path: Path) -> None:
    doc_text = (
        "Arztbrief Nuklearmedizin\n"
        "Behandelnder Arzt: Dr. med. Frank Weber <weber@praxis-nord.de>\n"
        "Telefon: +49 30 12345678\n"
        "Fachbereich: Radiologie und Schilddrüsensonographie\n"
    )
    record = SourceRecord(
        source_id="src_doc1",
        path=str(tmp_path / "doc1.txt"),
        display_name="doc1.txt",
        sha256="fake_sha",
        mime_type="text/plain",
    )
    out_dir = tmp_path / "out_contacts"
    out_dir.mkdir(parents=True)

    artifacts, read_ids, metadata = build_contact_monitor(
        (record,),
        {record.source_id: doc_text},
        out_dir,
        run_id="cm_test_1",
        since_run_id=None,
    )

    assert len(artifacts) == 3
    assert metadata["candidate_count"] == 1
    assert metadata["doctor_count"] == 1
    assert metadata["with_phone_count"] == 1

    json_path = out_dir / "contacts" / "cm_test_1.json"
    txt_path = out_dir / "contacts" / "cm_test_1.txt"
    md_path = out_dir / "contacts" / "cm_test_1.md"

    assert json_path.is_file()
    assert txt_path.is_file()
    assert md_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    cand = payload["candidates"][0]
    assert cand["email"] == "weber@praxis-nord.de"
    assert cand["name"] == "Dr. med. Frank Weber"
    assert "+49 30 12345678" in cand["phone"]
    assert cand["contact_class"] == "doctor"

    # Verify txt contact book can be parsed by read_contacts
    contacts, notes = read_contacts(txt_path)
    assert len(contacts) == 1
    assert contacts[0].name == "Dr. med. Frank Weber"
    assert contacts[0].contact_class == "doctor"
    assert contacts[0].email == "weber@praxis-nord.de"
    assert "+49 30 12345678" in contacts[0].phone


def test_recipient_bridge_resolves_name_to_email(tmp_path: Path) -> None:
    book_file = tmp_path / "contacts.txt"
    book_file.write_text(
        "name: Dr. med. Frank Weber · class: doctor · email: weber@praxis.de · "
        "phone: +49 30 123456 · note: Radiologie\n"
        "name: Dr. med. Sabine Becker · class: doctor · email: becker@labor.de · "
        "phone: 030-987654 · note: Labor\n",
        encoding="utf-8",
    )

    result = validate_recipient_bridge(
        contact_book_path=book_file,
        requested_recipients=["Dr. med. Frank Weber"],
        declared_right="draft_only",
        send_requested=False,
    )

    assert result.resolved_recipients == ("weber@praxis.de",)
    assert result.governing_right == "draft_only"
    assert result.send_permitted is False
    assert len(result.matched_contacts) == 1
    assert result.matched_contacts[0].email == "weber@praxis.de"


def test_recipient_bridge_ambiguous_name_raises(tmp_path: Path) -> None:
    book_file = tmp_path / "contacts.txt"
    book_file.write_text(
        "name: Dr. med. Frank Weber · class: doctor · email: frank@praxis.de · phone: 111\n"
        "name: Dr. med. Claudia Weber · class: doctor · email: claudia@praxis.de · phone: 222\n",
        encoding="utf-8",
    )

    with pytest.raises(RecipientBridgeError, match="ambiguous_recipient_in_contact_book"):
        validate_recipient_bridge(
            contact_book_path=book_file,
            requested_recipients=["Dr. Weber"],
            declared_right="draft_only",
        )


def test_recipient_bridge_missing_recipient_raises(tmp_path: Path) -> None:
    book_file = tmp_path / "contacts.txt"
    book_file.write_text(
        "name: Dr. med. Frank Weber · class: doctor · email: frank@praxis.de · phone: 111\n",
        encoding="utf-8",
    )

    with pytest.raises(RecipientBridgeError, match="recipient_not_found_in_contact_book"):
        validate_recipient_bridge(
            contact_book_path=book_file,
            requested_recipients=["Dr. Müller"],
            declared_right="draft_only",
        )

    with pytest.raises(RecipientBridgeError, match="recipient_bridge_recipient_missing"):
        validate_recipient_bridge(
            contact_book_path=book_file,
            requested_recipients=[],
            declared_right="draft_only",
        )


def test_recipient_bridge_live_send_forbidden(tmp_path: Path) -> None:
    book_file = tmp_path / "contacts.txt"
    book_file.write_text(
        "name: Dr. med. Frank Weber · class: doctor · email: frank@praxis.de · phone: 111\n",
        encoding="utf-8",
    )

    with pytest.raises(RecipientBridgeError, match="recipient_bridge_live_send_forbidden"):
        validate_recipient_bridge(
            contact_book_path=book_file,
            requested_recipients=["Dr. med. Frank Weber"],
            send_requested=True,
        )


def test_recipient_bridge_telegram_channel_forbidden(tmp_path: Path) -> None:
    book_file = tmp_path / "contacts.txt"
    book_file.write_text(
        "name: Dr. med. Frank Weber · class: doctor · email: frank@praxis.de · phone: 111\n",
        encoding="utf-8",
    )

    with pytest.raises(RecipientBridgeError, match="recipient_bridge_telegram_not_implemented"):
        validate_recipient_bridge(
            contact_book_path=book_file,
            requested_recipients=["Dr. med. Frank Weber"],
            channel="telegram",
        )


def test_g12_positive_voyage_full_chain(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir(parents=True)
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    out3 = tmp_path / "out3"

    doc = inbox / "01-arztbrief.pdf"
    doc.write_bytes(
        _render_pdf(
            "Arztbrief Nuklearmedizin\n"
            "Behandelnder Arzt: Dr. med. Frank Weber <weber@praxis.de>\n"
            "Telefon: +49 30 12345678\n"
            "Fachbereich: Radiologie und Schilddrüsendiagnostik\n"
            "Befund: Struma nodosa rechts.\n"
        )
    )

    plan = {
        "voyage_id": "vy_g12_pos_test",
        "title": "G12 Positive Test Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(inbox)],
                    "output_dir": str(out1),
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
                    "input_roots": [str(inbox)],
                    "output_dir": str(out2),
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
                    "input_roots": [str(inbox)],
                    "output_dir": str(out3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "from_address": "patient@example.org",
                        "subject": "Terminanfrage",
                        "body": "Bitte um Termin.",
                        "rights": "draft_only",
                        "send_requested": False,
                    },
                },
            },
        ],
    }

    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(plan, config, run_id="g12_pos_test")

    assert result.status == "executed"
    assert len(result.steps) == 3

    step2 = result.steps[1]
    assert (Path(step2.output_dir) / "contacts" / f"{step2.run_id}.txt").is_file()

    step3 = result.steps[2]
    draft_eml = Path(step3.output_dir) / "mail-drafts" / step3.run_id / "draft.eml"
    approval = Path(step3.output_dir) / "mail-drafts" / step3.run_id / "approval.json"
    assert draft_eml.is_file()
    assert approval.is_file()

    app_data = json.loads(approval.read_text(encoding="utf-8"))
    assert app_data["send_performed"] is False
    assert app_data["confirmation_required"] is True
