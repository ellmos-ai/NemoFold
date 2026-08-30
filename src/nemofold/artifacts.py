from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .contracts import ArtifactRecord, Claim, Coverage


def _locator_label(source_id: str, page: int | None, section: str | None) -> str:
    details = [source_id]
    if page is not None:
        details.append(f"page {page}")
    if section:
        details.append(f"section {section}")
    return ", ".join(details)


def render_markdown(title: str, claims: Sequence[Claim], coverage: Coverage) -> str:
    lines = [f"# {title}", ""]
    for claim in claims:
        lines.extend((f"## {claim.statement}", ""))
        lines.extend(
            (
                f"Conflict status: {claim.conflict_status}",
                f"Uncertainty: {claim.uncertainty:.3f}",
                "",
            )
        )
        if not claim.evidence:
            lines.extend(("Status: unverified; no source locator supplied.", ""))
        for locator in claim.evidence:
            label = _locator_label(locator.source_id, locator.page, locator.section)
            lines.extend((f'- [{label}] "{locator.quote}"', ""))
    lines.extend(
        (
            "## Coverage",
            "",
            f"- Sources: {coverage.total_sources}",
            f"- Read: {coverage.read_sources}",
            f"- Cited: {coverage.cited_sources}",
            f"- Unread: {', '.join(coverage.unread_source_ids) or 'none'}",
            f"- Read but uncited: {', '.join(coverage.uncited_read_source_ids) or 'none'}",
            "",
        )
    )
    return "\n".join(lines)


def render_text(title: str, claims: Sequence[Claim], coverage: Coverage) -> str:
    lines = [title, "=" * len(title), ""]
    for claim in claims:
        lines.append(claim.statement)
        lines.append(f"  Conflict status: {claim.conflict_status}")
        lines.append(f"  Uncertainty: {claim.uncertainty:.3f}")
        if not claim.evidence:
            lines.append("  Status: unverified; no source locator supplied.")
        for locator in claim.evidence:
            label = _locator_label(locator.source_id, locator.page, locator.section)
            lines.append(f'  [{label}] "{locator.quote}"')
        lines.append("")
    lines.extend(
        (
            "Coverage",
            f"  Sources: {coverage.total_sources}",
            f"  Read: {coverage.read_sources}",
            f"  Cited: {coverage.cited_sources}",
            f"  Unread: {', '.join(coverage.unread_source_ids) or 'none'}",
            f"  Read but uncited: {', '.join(coverage.uncited_read_source_ids) or 'none'}",
            "",
        )
    )
    return "\n".join(lines)


def write_text_artifact(path: str | Path, content: str, format_name: str) -> ArtifactRecord:
    return write_binary_artifact(path, content.encode("utf-8"), format_name)


def write_binary_artifact(
    path: str | Path,
    data: bytes,
    format_name: str,
) -> ArtifactRecord:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    try:
        with os.fdopen(handle, "wb") as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return ArtifactRecord(
        format=format_name,
        path=str(destination),
        sha256=hashlib.sha256(data).hexdigest(),
    )
