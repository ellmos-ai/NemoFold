from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from nemofold.application import (
    ExecutionConfig,
    authorize_send,
    release_send,
    run_job,
)
from nemofold.contracts import RunStatus
from nemofold.job_io import parse_job_payload
from nemofold.outbound import (
    CHANNEL_EMAIL,
    SendReceipt,
    SmtpAdapter,
    TelegramAdapter,
    class_rights_from,
    now,
    resolve_recipients,
    strictest,
)
from nemofold.structured_sources import read_contacts

CLASS_RIGHTS = {
    "familie": "send_when_ordered",
    "dienstlich": "send_with_confirmation",
    "oeffentlich": "draft_only",
}


@dataclass
class MockSmtp:
    """A local stand-in. No test in this suite opens a socket."""

    sent: list[dict[str, object]] = field(default_factory=list)
    channel: str = CHANNEL_EMAIL
    name: str = "mock-smtp"

    def readiness(self) -> tuple[bool, str]:
        return True, ""

    def send(
        self, *, recipients: tuple[str, ...], subject: str, body: str, digest: str
    ) -> SendReceipt:
        self.sent.append(
            {"recipients": list(recipients), "subject": subject, "digest": digest}
        )
        return SendReceipt(
            channel=CHANNEL_EMAIL,
            adapter="mock-smtp",
            accepted=True,
            recipients=recipients,
            detail=f"accepted for {len(recipients)} recipient(s)",
            sent_at=now(),
        )


@pytest.fixture
def contact_book(tmp_path: Path) -> Path:
    book = tmp_path / "kontakte.txt"
    book.write_text(
        "name: Ines Brandt · class: familie · email: ines@example.invalid\n"
        "name: Robert Ostwald · class: dienstlich · email: ostwald@example.invalid\n"
        "name: Liste Allgemein · class: oeffentlich · email: liste@example.invalid\n",
        encoding="utf-8",
    )
    return book


def _mail_job(tmp_path: Path, book: Path, to: list[str], **parameters):
    documents = tmp_path / "akte"
    documents.mkdir(exist_ok=True)
    (documents / "notiz.txt").write_text("Inhalt", encoding="utf-8")
    payload = {
        "from_address": "ich@example.invalid",
        "to": to,
        "cc": [],
        "subject": "Rückfrage",
        "body": "Bitte um Prüfung.",
        "attachment_source_ids": [],
        "send_requested": False,
        "contact_book": str(book),
        "recipient_class_rights": CLASS_RIGHTS,
    }
    payload.update(parameters)
    return parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "controlled_email",
            "input_roots": [str(documents)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": payload.pop("action_mode", "dry_run"),
            "parameters": payload,
        },
        base_dir=tmp_path,
    )


# --------------------------------------------------------------------------- #
# The class break
# --------------------------------------------------------------------------- #


def test_the_strictest_right_wins_over_a_set() -> None:
    assert strictest(("send_when_ordered", "draft_only")) == "draft_only"
    assert strictest(("send_when_ordered", "send_with_confirmation")) == (
        "send_with_confirmation"
    )
    assert strictest(()) == "draft_only"
    # An unknown value counts as the strictest rather than being ignored.
    assert strictest(("send_when_ordered", "nonsense")) == "draft_only"


def test_one_class_keeps_its_own_right(contact_book) -> None:
    contacts, _ = read_contacts(contact_book)

    decision = resolve_recipients(
        ("ines@example.invalid",),
        contacts,
        CLASS_RIGHTS,
        declared_right="send_when_ordered",
    )

    assert decision.right == "send_when_ordered"
    assert decision.class_break is False
    assert decision.classes == ("familie",)


def test_a_message_across_two_classes_is_governed_by_the_stricter(contact_book) -> None:
    contacts, _ = read_contacts(contact_book)

    decision = resolve_recipients(
        ("ines@example.invalid", "liste@example.invalid"),
        contacts,
        CLASS_RIGHTS,
        declared_right="send_when_ordered",
    )

    # One mail to a family address and a public list under the family rule is
    # the mistake this exists to prevent, and nobody notices it afterwards.
    assert decision.class_break is True
    assert decision.right == "draft_only"
    assert set(decision.classes) == {"familie", "oeffentlich"}
    assert "strictest of them governs it" in decision.reason


def test_an_unknown_recipient_counts_as_the_strictest_case(contact_book) -> None:
    contacts, _ = read_contacts(contact_book)

    decision = resolve_recipients(
        ("fremd@example.invalid",), contacts, CLASS_RIGHTS, declared_right="send_when_ordered"
    )

    assert decision.right == "draft_only"
    assert decision.unclassified == ("fremd@example.invalid",)
    assert "treated as the strictest case" in decision.reason


def test_a_declared_right_may_narrow_but_never_widen(contact_book) -> None:
    contacts, _ = read_contacts(contact_book)

    narrowed = resolve_recipients(
        ("ines@example.invalid",), contacts, CLASS_RIGHTS, declared_right="draft_only"
    )
    attempted = resolve_recipients(
        ("liste@example.invalid",), contacts, CLASS_RIGHTS, declared_right="send_when_ordered"
    )

    assert narrowed.right == "draft_only"
    assert attempted.right == "draft_only"


def test_an_unknown_right_in_the_class_map_is_refused() -> None:
    with pytest.raises(ValueError, match="must map to draft_only"):
        class_rights_from({"familie": "send_anything"})


# --------------------------------------------------------------------------- #
# The right decides what actually happens
# --------------------------------------------------------------------------- #


def test_draft_only_stops_at_the_draft(tmp_path, contact_book) -> None:
    job = _mail_job(tmp_path, contact_book, ["liste@example.invalid"], send_requested=True,
                    action_mode="apply")
    adapter = MockSmtp()
    authorize_send("draft_only", allowed=True, adapter=adapter)
    try:
        result = run_job(
            job,
            ExecutionConfig(allowed_roots=(str(tmp_path),), apply_actions_allowed=True),
            run_id="draft_only",
        )
    finally:
        release_send("draft_only")

    assert result.report.status is RunStatus.BLOCKED
    assert "right_is_draft_only" in result.report.errors
    assert adapter.sent == []


def test_send_with_confirmation_needs_the_exact_digest(tmp_path, contact_book) -> None:
    job = _mail_job(tmp_path, contact_book, ["ostwald@example.invalid"], send_requested=True,
                    action_mode="apply", confirmation_digest="wrong",
                    rights="send_with_confirmation")
    adapter = MockSmtp()
    authorize_send("wrong_digest", allowed=True, adapter=adapter)
    try:
        result = run_job(
            job,
            ExecutionConfig(allowed_roots=(str(tmp_path),), apply_actions_allowed=True),
            run_id="wrong_digest",
        )
    finally:
        release_send("wrong_digest")

    assert result.report.status is RunStatus.BLOCKED
    assert "confirmation_digest_mismatch" in result.report.errors
    assert adapter.sent == []


def test_send_with_confirmation_reaches_the_adapter_once_confirmed(
    tmp_path, contact_book
) -> None:
    # First run to learn the digest, exactly as a person would.
    first = run_job(
        _mail_job(tmp_path, contact_book, ["ostwald@example.invalid"]),
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="learn_digest",
    )
    digest = first.report.metadata["approval_digest"]

    job = _mail_job(
        tmp_path,
        contact_book,
        ["ostwald@example.invalid"],
        send_requested=True,
        action_mode="apply",
        confirmation_digest=digest,
        rights="send_with_confirmation",
    )
    adapter = MockSmtp()
    authorize_send("confirmed", allowed=True, adapter=adapter)
    try:
        result = run_job(
            job,
            ExecutionConfig(allowed_roots=(str(tmp_path),), apply_actions_allowed=True),
            run_id="confirmed",
        )
    finally:
        release_send("confirmed")

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["send_performed"] is True
    assert adapter.sent[0]["recipients"] == ["ostwald@example.invalid"]
    payload = json.loads((tmp_path / "out" / "confirmed.outbound.json").read_text("utf-8"))
    assert payload["right"] == "send_with_confirmation"
    assert payload["receipt"]["accepted"] is True


def test_send_when_ordered_needs_no_digest_but_still_needs_permission(
    tmp_path, contact_book
) -> None:
    job = _mail_job(tmp_path, contact_book, ["ines@example.invalid"], send_requested=True,
                    action_mode="apply", rights="send_when_ordered")

    # Without the per-run permission the same job blocks.
    blocked = run_job(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path),), apply_actions_allowed=True),
        run_id="unpermitted",
    )
    assert blocked.report.status is RunStatus.BLOCKED
    assert "send_not_allowed_on_this_server" in blocked.report.errors

    adapter = MockSmtp()
    authorize_send("ordered", allowed=True, adapter=adapter)
    try:
        result = run_job(
            job,
            ExecutionConfig(allowed_roots=(str(tmp_path),), apply_actions_allowed=True),
            run_id="ordered",
        )
    finally:
        release_send("ordered")

    assert result.report.status is RunStatus.EXECUTED
    assert len(adapter.sent) == 1


def test_a_class_break_stops_a_send_that_each_half_would_allow(tmp_path, contact_book) -> None:
    job = _mail_job(
        tmp_path,
        contact_book,
        ["ines@example.invalid", "liste@example.invalid"],
        send_requested=True,
        action_mode="apply",
        rights="send_when_ordered",
    )
    adapter = MockSmtp()
    authorize_send("broken_class", allowed=True, adapter=adapter)
    try:
        result = run_job(
            job,
            ExecutionConfig(allowed_roots=(str(tmp_path),), apply_actions_allowed=True),
            run_id="broken_class",
        )
    finally:
        release_send("broken_class")

    assert result.report.status is RunStatus.BLOCKED
    assert adapter.sent == []
    payload = json.loads((tmp_path / "out" / "broken_class.outbound.json").read_text("utf-8"))
    assert payload["class_break"] is True
    assert "not knowing must not mean going ahead" in payload["strictness_note"]


# --------------------------------------------------------------------------- #
# Real channels stay honestly unavailable
# --------------------------------------------------------------------------- #


def test_the_real_smtp_adapter_names_what_is_missing() -> None:
    ready, reason = SmtpAdapter().readiness()

    assert ready is False
    # "Not configured" and "not allowed" are different problems with different
    # fixes, so the message names the fields rather than a general failure.
    assert reason.startswith("smtp_not_configured:")
    assert "host" in reason and "sender" in reason and "port" in reason


def test_a_configured_smtp_adapter_still_refuses_to_transmit() -> None:
    adapter = SmtpAdapter(host="mail.example.invalid", port=587, sender="ich@example.invalid")

    ready, _ = adapter.readiness()

    assert ready is True
    with pytest.raises(Exception, match="smtp_send_not_enabled_on_this_build"):
        adapter.send(recipients=("x@example.invalid",), subject="s", body="b", digest="d")


def test_the_telegram_adapter_is_present_and_says_it_does_nothing() -> None:
    ready, reason = TelegramAdapter().readiness()

    assert ready is False
    assert reason == "telegram_adapter_not_implemented"


def test_a_job_that_declares_no_right_may_never_send(tmp_path, contact_book) -> None:
    # D-035's default is draft_only, and a message to a class that would allow
    # more still cannot go: both ceilings have to permit it.
    job = _mail_job(
        tmp_path,
        contact_book,
        ["ines@example.invalid"],
        send_requested=True,
        action_mode="apply",
    )
    adapter = MockSmtp()
    authorize_send("undeclared", allowed=True, adapter=adapter)
    try:
        result = run_job(
            job,
            ExecutionConfig(allowed_roots=(str(tmp_path),), apply_actions_allowed=True),
            run_id="undeclared",
        )
    finally:
        release_send("undeclared")

    assert result.report.status is RunStatus.BLOCKED
    assert "right_is_draft_only" in result.report.errors
    assert adapter.sent == []
