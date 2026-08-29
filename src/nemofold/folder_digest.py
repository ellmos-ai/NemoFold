from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .contracts import SourceRecord


@dataclass(frozen=True, slots=True)
class DocumentCard:
    source_id: str
    display_name: str
    summary: str
    status: str


@dataclass(frozen=True, slots=True)
class FolderDigest:
    cards: tuple[DocumentCard, ...]
    changed_source_ids: tuple[str, ...]
    gap_source_ids: tuple[str, ...]
    markdown: str


def _summary(text: str, max_sentences: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    return " ".join(sentences[:max_sentences])


def build_digest(
    records: Sequence[SourceRecord],
    source_texts: Mapping[str, str],
    *,
    max_sentences: int = 3,
) -> FolderDigest:
    if max_sentences < 1:
        raise ValueError("max_sentences must be positive")
    cards: list[DocumentCard] = []
    changed: list[str] = []
    gaps: list[str] = []

    for record in records:
        text = source_texts.get(record.source_id)
        if text is None or record.extraction_status in {"unreadable", "excluded_symlink"}:
            summary = f"unavailable ({record.extraction_status})"
            gaps.append(record.source_id)
        else:
            summary = _summary(text, max_sentences)
        if record.extraction_status in {"new", "changed"}:
            changed.append(record.source_id)
        cards.append(
            DocumentCard(
                source_id=record.source_id,
                display_name=record.display_name,
                summary=summary,
                status=record.extraction_status,
            )
        )

    lines = ["# Folder digest", "", "## Documents", ""]
    lines.extend(f"- {card.source_id} | {card.display_name} — {card.summary}" for card in cards)
    lines.extend(("", "## Changes in this run", ""))
    lines.extend(f"- {source_id}" for source_id in changed)
    if not changed:
        lines.append("- none")
    lines.extend(("", "## Coverage gaps", ""))
    lines.extend(f"- {source_id}" for source_id in gaps)
    if not gaps:
        lines.append("- none")
    lines.append("")
    return FolderDigest(
        cards=tuple(cards),
        changed_source_ids=tuple(changed),
        gap_source_ids=tuple(gaps),
        markdown="\n".join(lines),
    )
