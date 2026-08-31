"""Render a merged synopsis; the merging itself is a shared primitive.

merge_sections in primitives does the section-wise merge and the conflict
detection. This module keeps the workflow's own rendering, so the same merge can
serve a future voyage that wants a different output.
"""

from __future__ import annotations

from .primitives import MergeConflict, MergedDocument, MergedSection, merge_sections

DEFAULT_SECTION = "Document body"

# Names kept for the workflow's vocabulary; the shapes come from the core.
Synopsis = MergedDocument
Section = MergedSection
Conflict = MergeConflict


def merge_synopsis(source_ids: tuple[str, ...], texts: dict[str, str]) -> MergedDocument:
    """Adapter kept so the workflow reads in its own words."""
    return merge_sections(source_ids, texts)


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
            for value, anchor in conflict.values:
                lines.append(f"  - {value} — {anchor.source_id}, line {anchor.line}")
        lines.append("")
    for section in synopsis.sections:
        lines.extend([f"## {section.title}", ""])
        for paragraph in section.paragraphs:
            lines.append(
                f"{paragraph.text} "
                f"[{paragraph.anchor.source_id}:{paragraph.anchor.line}]"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
