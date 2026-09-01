"""D-031: composing a document from a template, through report-forge.

NemoFold renders reports it builds itself. Filling somebody's own .docx template
is a different job with its own accumulated knowledge - styles, fields, the
places Word keeps state - and report-forge already does it. So this module is an
adapter and nothing else: no template code is copied here, and only the finish
stage is used, which takes a prepared payload and a template and writes the
document.

The dependency is optional on purpose. A workspace that renders evidence should
not fail to start because a document template engine is missing, so a run
without it ends blocked with the exact install command rather than with an
import error, and the surface says the extra is not installed rather than
implying the feature does not exist.

Mail merge is the same finish stage run once per recipient, with the contact
source coming from the structured-source reader. Each document names the contact
it was composed for, because a folder of near-identical files nobody can tell
apart is its own kind of failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .structured_sources import Contact, read_contacts

EXTRA_NAME = "templates"
INSTALL_HINT = 'pip install "nemofold[templates]"'
MAX_RECIPIENTS = 500


class TemplateEngineUnavailable(RuntimeError):
    """Raised when the optional template engine is not installed."""


@dataclass(frozen=True, slots=True)
class EngineStatus:
    available: bool
    version: str
    reason: str

    def as_metadata(self) -> dict[str, object]:
        return {
            "template_engine": "report-forge",
            "template_engine_available": self.available,
            "template_engine_version": self.version,
            "template_engine_note": self.reason,
        }


def engine_status() -> EngineStatus:
    """Whether the optional engine is here, and what to do when it is not."""
    try:
        import report_forge  # noqa: PLC0415 - optional dependency, probed at call time
    except ImportError as exc:
        return EngineStatus(
            available=False,
            version="",
            reason=(
                f"the optional '{EXTRA_NAME}' extra is not installed, so no template "
                f"can be filled. Install it with: {INSTALL_HINT} ({exc})"
            ),
        )
    return EngineStatus(
        available=True,
        version=getattr(report_forge, "__version__", "unknown"),
        reason="",
    )


@dataclass(frozen=True, slots=True)
class ComposeRequest:
    """One document to compose: a template, a payload and where it goes."""

    template_path: str
    payload: dict[str, Any]
    output_dir: str
    basename: str
    recipient: str = ""


def validate_template(path: Any, *, allowed) -> str:
    """A template is a file inside the approved roots, like every other input."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("document_compose needs a template_path")
    if not allowed.path_allowed(path):
        raise PermissionError("the template is outside the configured allow roots")
    if not Path(path).is_file():
        raise ValueError(f"template not found: {path}")
    return path


def payload_for(
    fields: dict[str, Any], contact: Contact | None = None
) -> dict[str, Any]:
    """Merge the declared fields with one contact's own values.

    Contact values win over the shared fields, which is the whole point of a
    merge; a shared field silently overriding the recipient's name would produce
    five hundred letters to the same person.
    """
    merged = dict(fields)
    if contact is not None:
        merged.update(
            {
                "name": contact.name,
                "email": contact.email,
                "phone": contact.phone,
                "class": contact.contact_class,
                "note": contact.note,
            }
        )
    return merged


def plan_merge(
    fields: dict[str, Any],
    template_path: str,
    output_dir: str,
    *,
    contact_book: str = "",
    basename: str = "dokument",
) -> tuple[tuple[ComposeRequest, ...], tuple[str, ...]]:
    """One request per recipient, or a single one when no book was named."""
    if not contact_book:
        return (
            (
                ComposeRequest(
                    template_path=template_path,
                    payload=payload_for(fields),
                    output_dir=output_dir,
                    basename=basename,
                ),
            ),
            (),
        )
    contacts, notes = read_contacts(contact_book)
    if len(contacts) > MAX_RECIPIENTS:
        raise ValueError(f"a merge may not exceed {MAX_RECIPIENTS} recipients")
    requests = tuple(
        ComposeRequest(
            template_path=template_path,
            payload=payload_for(fields, contact),
            output_dir=output_dir,
            # The file names the person, so a folder of near-identical documents
            # stays sortable by the only thing that distinguishes them.
            basename=f"{basename}-{_slug(contact.name)}",
            recipient=contact.name,
        )
        for contact in contacts
    )
    return requests, notes


def _slug(value: str) -> str:
    kept = [
        character.casefold() if character.isalnum() else "-" for character in value
    ]
    return "".join(kept).strip("-")[:40] or "empfaenger"


def compose_documents(
    requests: tuple[ComposeRequest, ...], *, status: EngineStatus | None = None
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Fill the template once per request. Returns written paths and notes.

    The payload is handed to report-forge's finish stage as JSON, which is the
    interface it already offers; nothing about how a template is filled is
    reimplemented here.
    """
    state = status or engine_status()
    if not state.available:
        raise TemplateEngineUnavailable(state.reason)
    from report_forge import ReportWorkflow  # noqa: PLC0415 - optional dependency

    workflow = ReportWorkflow()
    written: list[str] = []
    notes: list[str] = []
    for request in requests:
        output = Path(request.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        payload_path = output / f"{request.basename}.payload.json"
        payload_path.write_text(
            json.dumps(request.payload, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        try:
            result = workflow.finish(
                session_dir=str(output),
                llm_json_path=str(payload_path),
                output_folder=str(output),
                template_path=request.template_path,
            )
        except Exception as exc:  # noqa: BLE001 - the engine's failures are reported
            notes.append(f"{request.basename}: the template engine refused ({exc})")
            continue
        for candidate in ("document_path", "output_path", "path"):
            value = getattr(result, candidate, None)
            if value:
                written.append(str(value))
                break
        else:
            notes.append(
                f"{request.basename}: the engine returned no document path, so nothing "
                "is claimed to have been written."
            )
    return tuple(written), tuple(notes)


def compose_payload(
    requests: tuple[ComposeRequest, ...],
    written: tuple[str, ...],
    notes: tuple[str, ...],
    status: EngineStatus,
) -> dict[str, object]:
    return {
        "schema": "nemofold.document-compose.v1",
        "engine": "report-forge",
        "engine_available": status.available,
        "engine_note": status.reason,
        "requested": len(requests),
        "written": len(written),
        "documents": list(written),
        "recipients": [item.recipient for item in requests if item.recipient],
        "notes": list(notes),
        "boundary_note": (
            "NemoFold hands a payload and a template to report-forge and reports what "
            "came back. It does not fill templates itself, and a document the engine "
            "did not confirm is not listed as written."
        ),
    }
