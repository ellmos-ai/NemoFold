from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from pathlib import Path
from typing import Any, cast

from .artifacts import write_binary_artifact, write_text_artifact
from .contracts import ArtifactRecord, SourceRecord

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@dataclass(frozen=True, slots=True)
class MailAttachment:
    filename: str
    content_type: str
    data: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class ParsedMail:
    source_id: str
    display_name: str
    subject: str
    sender: str
    recipients: tuple[str, ...]
    date: str
    message_id: str
    body_text: str
    attachments: tuple[MailAttachment, ...]


@dataclass(frozen=True, slots=True)
class DraftResult:
    records: tuple[ArtifactRecord, ...]
    approval_digest: str
    attachment_source_ids: tuple[str, ...]


def _safe_filename(value: str, *, fallback: str) -> str:
    name = Path(value.replace("\\", "/")).name.strip()
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned[:180]


def _header(message: Message, name: str) -> str:
    value = message.get(name)
    return str(value).strip() if value is not None else ""


def _mail_body(message: EmailMessage) -> str:
    if message.is_multipart():
        plain = message.get_body(preferencelist=("plain",))
        if plain is None:
            return ""
        try:
            return plain.get_content().strip()
        except (LookupError, UnicodeError):
            return ""
    try:
        content = message.get_content()
    except (LookupError, UnicodeError):
        return ""
    return content.strip() if isinstance(content, str) else ""


def parse_eml(record: SourceRecord) -> ParsedMail:
    message = cast(
        EmailMessage,
        BytesParser(policy=policy.default).parsebytes(Path(record.path).read_bytes()),
    )
    attachments: list[MailAttachment] = []
    for index, part in enumerate(message.iter_attachments(), start=1):
        payload = part.get_payload(decode=True)
        data = payload if isinstance(payload, bytes) else b""
        filename = _safe_filename(
            part.get_filename() or f"attachment-{index}.bin",
            fallback=f"attachment-{index}.bin",
        )
        attachments.append(
            MailAttachment(
                filename=filename,
                content_type=part.get_content_type(),
                data=data,
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )
    recipients = tuple(
        value
        for field in ("to", "cc")
        for value in (_header(message, field),)
        if value
    )
    return ParsedMail(
        source_id=record.source_id,
        display_name=record.display_name,
        subject=_header(message, "subject"),
        sender=_header(message, "from"),
        recipients=recipients,
        date=_header(message, "date"),
        message_id=_header(message, "message-id"),
        body_text=_mail_body(message),
        attachments=tuple(attachments),
    )


def build_mail_case(
    records: tuple[SourceRecord, ...],
    output_dir: str | Path,
    *,
    run_id: str,
    case_id: str,
    case_title: str,
    include_attachments: bool,
) -> tuple[tuple[ArtifactRecord, ...], tuple[str, ...], dict[str, object]]:
    safe_case_id = _safe_filename(case_id, fallback=f"case-{run_id}")
    case_root = Path(output_dir) / "cases" / safe_case_id / run_id
    parsed: list[ParsedMail] = []
    omitted: list[dict[str, str]] = []
    artifacts: list[ArtifactRecord] = []
    for record in records:
        if Path(record.path).suffix.casefold() != ".eml":
            continue
        try:
            mail = parse_eml(record)
        except (OSError, ValueError, UnicodeError) as exc:
            omitted.append(
                {
                    "source_id": record.source_id,
                    "display_name": record.display_name,
                    "reason": type(exc).__name__,
                }
            )
            continue
        parsed.append(mail)
        if include_attachments:
            for index, attachment in enumerate(mail.attachments, start=1):
                target = (
                    case_root
                    / "attachments"
                    / f"{mail.source_id}-{index:02d}-{attachment.filename}"
                )
                artifacts.append(write_binary_artifact(target, attachment.data, "mail-attachment"))
    if not parsed:
        raise ValueError("mail_to_case requires at least one readable .eml source")

    messages_payload = [
        {
            "source_id": mail.source_id,
            "display_name": mail.display_name,
            "source_sha256": next(
                record.sha256 for record in records if record.source_id == mail.source_id
            ),
            "subject": mail.subject,
            "from": mail.sender,
            "to_or_cc": list(mail.recipients),
            "date": mail.date,
            "message_id": mail.message_id,
            "body_text": mail.body_text,
            "attachments": [
                {
                    "filename": item.filename,
                    "content_type": item.content_type,
                    "sha256": item.sha256,
                    "size_bytes": len(item.data),
                }
                for item in mail.attachments
            ],
        }
        for mail in parsed
    ]
    manifest = {
        "schema": "nemofold.mail-case.v1",
        "run_id": run_id,
        "case_id": safe_case_id,
        "title": case_title,
        "source_files_unchanged": True,
        "messages": messages_payload,
        "omissions": omitted,
    }
    artifacts.append(
        write_text_artifact(
            case_root / "case.json",
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            "mail-case-manifest",
        )
    )
    markdown = [f"# {case_title}", "", f"Case ID: `{safe_case_id}`", ""]
    for mail in parsed:
        markdown.extend(
            (
                f"## {mail.subject or '(no subject)'}",
                "",
                f"- Source: `{mail.display_name}` (`{mail.source_id}`)",
                f"- From: {mail.sender or '(missing)'}",
                f"- To/Cc: {'; '.join(mail.recipients) or '(missing)'}",
                f"- Date: {mail.date or '(missing)'}",
                f"- Attachments: {len(mail.attachments)}",
                "",
                mail.body_text or "_(No readable plain-text body.)_",
                "",
            )
        )
    artifacts.append(
        write_text_artifact(case_root / "case.md", "\n".join(markdown), "mail-case-report")
    )
    return (
        tuple(artifacts),
        tuple(mail.source_id for mail in parsed),
        {
            "case_id": safe_case_id,
            "message_count": len(parsed),
            "attachment_count": sum(len(mail.attachments) for mail in parsed),
            "omitted_message_count": len(omitted),
            "source_files_unchanged": True,
        },
    )


def _string_list(
    parameters: dict[str, Any], name: str, *, required: bool = False
) -> tuple[str, ...]:
    value = parameters.get(name, [])
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{name} must be a list of non-empty strings")
    normalized = tuple(item.strip() for item in value)
    if required and not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def build_controlled_draft(
    records: tuple[SourceRecord, ...],
    output_dir: str | Path,
    parameters: dict[str, Any],
    *,
    run_id: str,
) -> DraftResult:
    sender = parameters.get("from_address")
    subject = parameters.get("subject")
    body = parameters.get("body")
    if not isinstance(sender, str) or not EMAIL_PATTERN.fullmatch(sender.strip()):
        raise ValueError("from_address must be one email address")
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("subject must be a non-empty string")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("body must be a non-empty string")
    to = _string_list(parameters, "to", required=True)
    cc = _string_list(parameters, "cc")
    if any(not EMAIL_PATTERN.fullmatch(item) for item in (*to, *cc)):
        raise ValueError("to and cc entries must be email addresses")

    requested_ids = _string_list(parameters, "attachment_source_ids")
    by_id = {record.source_id: record for record in records}
    if any(source_id not in by_id for source_id in requested_ids):
        raise ValueError("attachment_source_ids contains an unknown approved source")
    selected = tuple(by_id[source_id] for source_id in requested_ids)
    if any(not Path(record.path).is_file() for record in selected):
        raise ValueError("every selected attachment must be a readable file")

    canonical = {
        "from": sender.strip(),
        "to": list(to),
        "cc": list(cc),
        "subject": subject.strip(),
        "body": body,
        "attachments": [
            {
                "source_id": record.source_id,
                "sha256": record.sha256,
                "display_name": record.display_name,
            }
            for record in selected
        ],
    }
    approval_digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    message = EmailMessage(policy=policy.SMTP)
    message["From"] = sender.strip()
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject.strip()
    message["X-NemoFold-Approval-Digest"] = approval_digest
    message.set_content(body)
    for record in selected:
        maintype, _, subtype = record.mime_type.partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        message.add_attachment(
            Path(record.path).read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=_safe_filename(record.display_name, fallback=f"{record.source_id}.bin"),
        )
    message.set_boundary(f"nemofold-{approval_digest[:24]}")

    draft_root = Path(output_dir) / "mail-drafts" / run_id
    draft = write_binary_artifact(draft_root / "draft.eml", message.as_bytes(), "email-draft")
    receipt = write_text_artifact(
        draft_root / "approval.json",
        json.dumps(
            {
                "schema": "nemofold.mail-approval.v1",
                "run_id": run_id,
                "approval_digest": approval_digest,
                "draft_sha256": draft.sha256,
                "recipient_count": len(to) + len(cc),
                "attachment_source_ids": list(requested_ids),
                "send_performed": False,
                "confirmation_required": True,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "mail-approval-receipt",
    )
    return DraftResult((draft, receipt), approval_digest, requested_ids)
