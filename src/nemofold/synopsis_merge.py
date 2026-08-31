"""Merge several documents into one synopsis without losing who said what.

Every paragraph keeps the source and line it came from, and where two sources
give a different answer under the same label the synopsis shows both in a
conflict block instead of silently preferring one. Merging is where provenance
is usually lost; here it is the part that is kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(?P<title>\S.*?)\s*#*\s*$")
LABELLED = re.compile(r"^\s*(?P<label>[^:#]{2,60}?)\s*:\s*(?P<value>\S.*?)\s*$")
DEFAULT_SECTION = "Document body"
MAX_PARAGRAPH_CHARS = 800
MAX_SECTIONS = 200


@dataclass(frozen=True, slots=True)
class Paragraph:
    text: str
    source_id: str
    line: int


@dataclass(frozen=True, slots=True)
class ConflictValue:
    value: str
    source_id: str
    line: int


@dataclass(frozen=True, slots=True)
class Conflict:
    section: str
    label: str
    values: tuple[ConflictValue, ...]


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    paragraphs: tuple[Paragraph, ...]


@dataclass(frozen=True, slots=True)
class Synopsis:
    sections: tuple[Section, ...]
    conflicts: tuple[Conflict, ...]
    source_ids: tuple[str, ...]

    @property
    def paragraph_count(self) -> int:
        return sum(len(section.paragraphs) for section in self.sections)


def _sections_of(text: str, fallback_title: str) -> list[tuple[str, list[tuple[int, str]]]]:
    """Split one document into (title, [(line, paragraph)]) sections."""
    sections: list[tuple[str, list[tuple[int, str]]]] = []
    current_title = fallback_title
    current: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        heading = HEADING.match(raw)
        if heading is not None:
            if current:
                sections.append((current_title, current))
                current = []
            current_title = heading.group("title")
            continue
        line = raw.strip()
        if line:
            current.append((number, line[:MAX_PARAGRAPH_CHARS]))
    if current:
        sections.append((current_title, current))
    return sections


def merge_synopsis(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
) -> Synopsis:
    """Merge every readable source into one section-wise synopsis.

    Documents without headings share the default section on purpose: merging
    them into one body is the point, and each paragraph keeps its own anchor
    so the shared section never blurs who wrote what.
    """
    ordered_titles: list[str] = []
    grouped: dict[str, list[Paragraph]] = {}
    labelled: dict[tuple[str, str], list[ConflictValue]] = {}
    used_sources: list[str] = []

    for source_id in source_ids:
        text = texts.get(source_id)
        if text is None:
            continue
        used_sources.append(source_id)
        for title, entries in _sections_of(text, DEFAULT_SECTION):
            key = title.casefold()
            if key not in grouped:
                if len(ordered_titles) >= MAX_SECTIONS:
                    continue
                ordered_titles.append(title)
                grouped[key] = []
            for line, paragraph in entries:
                grouped[key].append(
                    Paragraph(text=paragraph, source_id=source_id, line=line)
                )
                match = LABELLED.match(paragraph)
                if match is None:
                    continue
                label = match.group("label").strip()
                labelled.setdefault((key, label.casefold()), []).append(
                    ConflictValue(
                        value=match.group("value").strip(),
                        source_id=source_id,
                        line=line,
                    )
                )

    conflicts: list[Conflict] = []
    for (section_key, label_key), values in labelled.items():
        distinct = {item.value.casefold() for item in values}
        if len(distinct) < 2:
            continue
        section_title = next(
            (title for title in ordered_titles if title.casefold() == section_key),
            section_key,
        )
        conflicts.append(
            Conflict(
                section=section_title,
                label=label_key,
                values=tuple(values),
            )
        )

    sections = tuple(
        Section(title=title, paragraphs=tuple(grouped[title.casefold()]))
        for title in ordered_titles
    )
    return Synopsis(
        sections=sections,
        conflicts=tuple(sorted(conflicts, key=lambda item: (item.section, item.label))),
        source_ids=tuple(dict.fromkeys(used_sources)),
    )


def synopsis_markdown(synopsis: Synopsis, *, title: str) -> str:
    lines = [f"# {title}", ""]
    if synopsis.conflicts:
        lines.extend(
            [
                f"## Conflicts ({len(synopsis.conflicts)})",
                "",
                "The sources disagree under these labels. Both readings are kept; "
                "nothing was preferred automatically.",
                "",
            ]
        )
        for conflict in synopsis.conflicts:
            lines.append(f"- **{conflict.label}** in _{conflict.section}_")
            for value in conflict.values:
                lines.append(f"  - {value.value} — {value.source_id}, line {value.line}")
        lines.append("")
    for section in synopsis.sections:
        lines.extend([f"## {section.title}", ""])
        for paragraph in section.paragraphs:
            lines.append(f"{paragraph.text} [{paragraph.source_id}:{paragraph.line}]")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
