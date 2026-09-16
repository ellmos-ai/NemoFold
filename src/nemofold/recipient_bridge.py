"""Validated recipient bridge for Gate G12: Export Contacts and Controlled Email Drafts.

Bridges extracted contacts (nemofold.contacts.v1 / contact-book) into controlled email
parameters with strict recipient resolution, ambiguity checks, and fail-closed send gates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .structured_sources import Contact, read_contacts

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class RecipientBridgeError(RuntimeError):
    """Raised when the recipient bridge encounters an ambiguity or policy violation."""


@dataclass(frozen=True, slots=True)
class RecipientBridgeResult:
    """Outcome of validating and resolving recipients across the contact bridge."""

    resolved_recipients: tuple[str, ...]
    matched_contacts: tuple[Contact, ...]
    governing_right: str
    send_permitted: bool
    payload: dict[str, Any]


def _name_tokens(name: str) -> set[str]:
    cleaned = re.sub(r"(?i)\b(dr|prof|med|herr|frau)\b[.]?", "", name)
    return {t.casefold() for t in re.split(r"[\s,.-]+", cleaned) if len(t) > 1}


def resolve_bridge_recipients(
    contacts: tuple[Contact, ...],
    requested: tuple[str, ...] | list[str],
    *,
    require_known: bool = True,
    strict_doctor_class: bool = False,
) -> tuple[tuple[str, ...], tuple[Contact, ...]]:
    """Resolve names or email addresses against contacts with ambiguity checks."""
    if not requested:
        raise RecipientBridgeError("recipient_bridge_recipient_missing")

    resolved_emails: list[str] = []
    matched_contacts: list[Contact] = []

    for item in requested:
        target = item.strip()
        if not target:
            continue

        if EMAIL_PATTERN.fullmatch(target):
            # Direct email address lookup
            matches = [c for c in contacts if c.email.casefold() == target.casefold()]
            if not matches:
                if require_known:
                    raise RecipientBridgeError(f"recipient_not_in_contact_book:{target}")
                resolved_emails.append(target)
                continue
            contact = matches[0]
            if strict_doctor_class and contact.contact_class != "doctor":
                raise RecipientBridgeError(f"recipient_not_a_doctor:{target}")
            resolved_emails.append(contact.email)
            matched_contacts.append(contact)
        else:
            # Name lookup (case-insensitive exact, substring or title-stripped token match)
            target_norm = target.casefold()
            exact_matches = [
                c for c in contacts if c.name.casefold() == target_norm
            ]
            if len(exact_matches) == 1:
                matches = exact_matches
            else:
                sub_matches = [
                    c
                    for c in contacts
                    if target_norm in c.name.casefold() or c.name.casefold() in target_norm
                ]
                if sub_matches:
                    matches = sub_matches
                else:
                    target_tokens = _name_tokens(target)
                    if target_tokens:
                        matches = [
                            c
                            for c in contacts
                            if target_tokens.issubset(_name_tokens(c.name))
                        ]
                    else:
                        matches = []

            if not matches:
                raise RecipientBridgeError(f"recipient_not_found_in_contact_book:{target}")
            if len(matches) > 1:
                matched_names = [c.name for c in matches]
                raise RecipientBridgeError(
                    f"ambiguous_recipient_in_contact_book:{target}:matches={matched_names}"
                )

            contact = matches[0]
            if not contact.email or not EMAIL_PATTERN.fullmatch(contact.email):
                raise RecipientBridgeError(
                    f"recipient_contact_has_no_valid_email:{contact.name}"
                )
            if strict_doctor_class and contact.contact_class != "doctor":
                raise RecipientBridgeError(f"recipient_not_a_doctor:{contact.name}")

            resolved_emails.append(contact.email)
            matched_contacts.append(contact)

    if not resolved_emails:
        raise RecipientBridgeError("recipient_bridge_recipient_missing")

    return tuple(resolved_emails), tuple(matched_contacts)


def validate_recipient_bridge(
    contact_book_path: Path | str,
    requested_recipients: tuple[str, ...] | list[str],
    *,
    declared_right: str = "draft_only",
    send_requested: bool = False,
    channel: str = "email",
    require_known: bool = True,
    strict_doctor_class: bool = False,
) -> RecipientBridgeResult:
    """Validate recipient bridge contract fail-closed."""
    if send_requested:
        raise RecipientBridgeError("recipient_bridge_live_send_forbidden")

    if str(channel).strip().casefold() == "telegram":
        raise RecipientBridgeError("recipient_bridge_telegram_not_implemented")

    if declared_right != "draft_only":
        raise RecipientBridgeError(f"recipient_bridge_right_forbidden:{declared_right}")

    path = Path(contact_book_path)
    if not path.is_file():
        raise RecipientBridgeError(f"contact_book_file_not_found:{path}")

    contacts, notes = read_contacts(path)
    if not contacts:
        raise RecipientBridgeError("contact_book_has_no_valid_contacts")

    recipients = tuple(requested_recipients)
    resolved_emails, matched = resolve_bridge_recipients(
        contacts,
        recipients,
        require_known=require_known,
        strict_doctor_class=strict_doctor_class,
    )

    payload = {
        "schema": "nemofold.recipient-bridge.v1",
        "contact_book": str(path),
        "requested_recipients": list(recipients),
        "resolved_recipients": list(resolved_emails),
        "matched_contacts": [
            {
                "name": c.name,
                "email": c.email,
                "phone": c.phone,
                "class": c.contact_class,
                "note": c.note,
                "line": c.line,
            }
            for c in matched
        ],
        "governing_right": "draft_only",
        "send_permitted": False,
        "channel": channel,
        "notes": list(notes),
    }

    return RecipientBridgeResult(
        resolved_recipients=resolved_emails,
        matched_contacts=matched,
        governing_right="draft_only",
        send_permitted=False,
        payload=payload,
    )
