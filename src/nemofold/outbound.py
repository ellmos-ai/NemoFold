"""D-035 evaluated: what a right actually permits, and who the recipient is.

Until now ``rights`` was a stored field. Here it decides something, and the
decision has three parts that must not be collapsed.

**The right itself.** ``draft_only`` stops at the draft. ``send_with_confirmation``
reaches the adapter, but only after the exact approval digest comes back.
``send_when_ordered`` reaches it on the order alone. Each step up is a smaller
promise about how much a person still sees.

**The recipient.** A right is not a property of a message, it is a property of a
message *to somebody*. Recipient classes come from the local contact book, and a
class nobody declared is treated as the strictest case rather than the
friendliest - the one place where "we do not know" must not become "go ahead".

**The class break.** A message addressed across two classes is governed by the
strictest of them. Sending one mail to a family address and a public list under
the family rule is exactly the mistake this exists to prevent, and it is a
mistake nobody notices afterwards.

The adapter itself is an interface with a mock behind it in tests. A real send
stays blocked until a server is configured and a person allows it, and the
status says which of the two is missing rather than reporting a general
unavailability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from .model_authority import (
    RIGHTS_DRAFT_ONLY,
    RIGHTS_SEND_WHEN_ORDERED,
    RIGHTS_SEND_WITH_CONFIRMATION,
)
from .structured_sources import Contact

# Strictest first. The order is the whole point of the class-break rule, so it
# lives in one place rather than being re-derived at each comparison.
RIGHTS_ORDER = (
    RIGHTS_DRAFT_ONLY,
    RIGHTS_SEND_WITH_CONFIRMATION,
    RIGHTS_SEND_WHEN_ORDERED,
)

UNCLASSIFIED = "(unclassified)"
CHANNEL_EMAIL = "email"
CHANNEL_TELEGRAM = "telegram"


class OutboundError(RuntimeError):
    """Raised when a permitted send could not be carried out."""


@dataclass(frozen=True, slots=True)
class RecipientDecision:
    """The right that governs this message, and why it is that one."""

    right: str
    classes: tuple[str, ...]
    unclassified: tuple[str, ...]
    class_break: bool
    reason: str


def strictest(rights: tuple[str, ...]) -> str:
    """The narrowest of several rights. Unknown values count as the narrowest."""
    best = len(RIGHTS_ORDER) - 1
    for right in rights:
        index = RIGHTS_ORDER.index(right) if right in RIGHTS_ORDER else 0
        best = min(best, index)
    return RIGHTS_ORDER[best] if rights else RIGHTS_DRAFT_ONLY


def resolve_recipients(
    addresses: tuple[str, ...],
    contacts: tuple[Contact, ...],
    class_rights: dict[str, str],
    *,
    declared_right: str = RIGHTS_DRAFT_ONLY,
) -> RecipientDecision:
    """Decide the governing right for one message to these addresses.

    The declared right is a ceiling, never a floor: a voyage may narrow what a
    recipient class allows, and may not widen it.
    """
    by_address = {item.email.casefold(): item for item in contacts if item.email}
    classes: list[str] = []
    unknown: list[str] = []
    for address in addresses:
        contact = by_address.get(address.casefold())
        if contact is None or not contact.contact_class:
            unknown.append(address)
            classes.append(UNCLASSIFIED)
            continue
        classes.append(contact.contact_class)
    rights = [
        class_rights.get(name, RIGHTS_DRAFT_ONLY) if name != UNCLASSIFIED
        else RIGHTS_DRAFT_ONLY
        for name in classes
    ]
    governing = strictest((*rights, declared_right))
    distinct = tuple(dict.fromkeys(classes))
    class_break = len(distinct) > 1
    if class_break:
        reason = (
            "this message is addressed across "
            + ", ".join(distinct)
            + f", so the strictest of them governs it: {governing}"
        )
    elif unknown:
        reason = (
            "at least one recipient is not in the contact book, and an undeclared "
            f"recipient is treated as the strictest case: {governing}"
        )
    else:
        reason = f"every recipient is {distinct[0] if distinct else 'unknown'}: {governing}"
    return RecipientDecision(
        right=governing,
        classes=distinct,
        unclassified=tuple(unknown),
        class_break=class_break,
        reason=reason,
    )


@dataclass(frozen=True, slots=True)
class SendReceipt:
    """What the adapter did, in a form a ledger can carry."""

    channel: str
    adapter: str
    accepted: bool
    recipients: tuple[str, ...]
    detail: str
    sent_at: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema": "nemofold.send-receipt.v1",
            "channel": self.channel,
            "adapter": self.adapter,
            "accepted": self.accepted,
            "recipient_count": len(self.recipients),
            "detail": self.detail,
            "sent_at": self.sent_at,
        }


class OutboundAdapter(Protocol):
    """One channel out. Readiness is asked, never assumed."""

    @property
    def channel(self) -> str: ...

    @property
    def name(self) -> str: ...

    def readiness(self) -> tuple[bool, str]: ...

    def send(
        self, *, recipients: tuple[str, ...], subject: str, body: str, digest: str
    ) -> SendReceipt: ...


@dataclass(frozen=True, slots=True)
class SmtpAdapter:
    """A real SMTP channel, unavailable until it is configured.

    It reports which piece is missing rather than a general unavailability,
    because "not configured" and "not allowed" are different problems with
    different fixes and only one of them is the user's to make.
    """

    host: str = ""
    port: int = 0
    sender: str = ""
    channel: str = CHANNEL_EMAIL
    name: str = "smtp"

    def readiness(self) -> tuple[bool, str]:
        missing = [
            label
            for label, value in (("host", self.host), ("sender", self.sender))
            if not str(value).strip()
        ]
        if self.port <= 0:
            missing.append("port")
        if missing:
            return False, "smtp_not_configured:" + ",".join(missing)
        return True, ""

    def send(
        self, *, recipients: tuple[str, ...], subject: str, body: str, digest: str
    ) -> SendReceipt:
        ready, reason = self.readiness()
        if not ready:
            raise OutboundError(reason)
        # A real transmission is deliberately not implemented here. Wiring an
        # actual socket without a person having configured and allowed this
        # server would be the one step this product never takes on its own.
        raise OutboundError("smtp_send_not_enabled_on_this_build")


@dataclass(frozen=True, slots=True)
class TelegramAdapter:
    """The second channel of the same shape, honestly unavailable.

    It exists so the pattern is visible and the surface can say what is missing,
    not so that anything can be sent. An adapter that pretended to work would be
    worse than none.
    """

    channel: str = CHANNEL_TELEGRAM
    name: str = "telegram"

    def readiness(self) -> tuple[bool, str]:
        return False, "telegram_adapter_not_implemented"

    def send(
        self, *, recipients: tuple[str, ...], subject: str, body: str, digest: str
    ) -> SendReceipt:
        raise OutboundError("telegram_adapter_not_implemented")


@dataclass(frozen=True, slots=True)
class SendDecision:
    """Whether this message may be sent, and every reason it may not."""

    allowed: bool
    reasons: tuple[str, ...]
    right: str
    recipients: RecipientDecision

    def as_metadata(self) -> dict[str, object]:
        return {
            "outbound_right": self.right,
            "outbound_allowed": self.allowed,
            "outbound_blocked_reasons": list(self.reasons),
            "recipient_classes": list(self.recipients.classes),
            "recipient_class_break": self.recipients.class_break,
            "recipient_rule": self.recipients.reason,
            "send_performed": False,
        }


def evaluate_send(
    *,
    recipients: RecipientDecision,
    send_requested: bool,
    apply_mode: bool,
    approval_digest: str,
    confirmation_digest: str,
    adapter_ready: bool,
    adapter_reason: str,
    user_allows_send: bool,
) -> SendDecision:
    """Collect every reason this message may not leave, not only the first."""
    reasons: list[str] = []
    right = recipients.right
    if not send_requested:
        reasons.append("no_send_was_requested")
    if right == RIGHTS_DRAFT_ONLY:
        reasons.append("right_is_draft_only")
    if not apply_mode:
        reasons.append("send_requires_apply_mode")
    if not user_allows_send:
        reasons.append("send_not_allowed_on_this_server")
    if not adapter_ready:
        reasons.append(adapter_reason or "outbound_adapter_not_ready")
    if right == RIGHTS_SEND_WITH_CONFIRMATION:
        if not confirmation_digest:
            reasons.append("confirmation_digest_required")
        elif confirmation_digest != approval_digest:
            reasons.append("confirmation_digest_mismatch")
    return SendDecision(
        allowed=not reasons,
        reasons=tuple(reasons),
        right=right,
        recipients=recipients,
    )


def send_payload(decision: SendDecision, receipt: SendReceipt | None) -> dict[str, object]:
    return {
        "schema": "nemofold.outbound.v1",
        "right": decision.right,
        "allowed": decision.allowed,
        "blocked_reasons": list(decision.reasons),
        "recipient_classes": list(decision.recipients.classes),
        "unclassified_recipients": list(decision.recipients.unclassified),
        "class_break": decision.recipients.class_break,
        "governing_rule": decision.recipients.reason,
        "receipt": receipt.as_payload() if receipt else None,
        "strictness_note": (
            "A message addressed across two classes is governed by the strictest of "
            "them, and a recipient nobody classified counts as the strictest case. "
            "This is the one place where not knowing must not mean going ahead."
        ),
    }


def receipt_json(receipt: SendReceipt) -> str:
    return json.dumps(receipt.as_payload(), indent=2, sort_keys=True) + "\n"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def class_rights_from(value: Any) -> dict[str, str]:
    """Read the declared class-to-right mapping, refusing an unknown right."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("recipient_class_rights must be an object")
    mapping: dict[str, str] = {}
    for name, right in value.items():
        if not isinstance(name, str) or right not in RIGHTS_ORDER:
            raise ValueError(
                "every recipient class must map to draft_only, "
                "send_with_confirmation or send_when_ordered"
            )
        mapping[name] = right
    return mapping
