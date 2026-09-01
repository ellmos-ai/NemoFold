"""Compositions: a guide, a wiki, and the patterns hiding in a pile of logs.

Three workflows that add no new reasoning. They are arrangements of primitives
that already exist - section merge, deduplication, staged aggregation - and each
one earns its place by producing a shape somebody actually reads.

The guide is a compilation, not a rewrite. Every paragraph is a line from a
source with its anchor, folded so the same instruction is not repeated eight
times, and the front matter lists which documents it stands in for. A guide that
paraphrased its sources would be a new document nobody could check against the
old ones, which is the opposite of replacing them.

The wiki is the same corpus with its structure made walkable: one page per
document, an index that links them, and every heading kept. Nothing is
summarised, because a wiki whose pages disagree with the files they came from is
worse than no wiki.

Pattern mining reports what recurs, with how often and where. A recurring line is
a finding about the corpus, never a rule about the world: three thousand logs
saying "Ticket geschlossen" tell you that phrase is used, not that it should be.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .primitives import (
    AggregationBudget,
    AnchoredStatement,
    MergedDocument,
    aggregate_mapreduce,
    deduplicate,
    merge_sections,
    statements_from_texts,
)

MAX_PAGES = 500
MAX_SECTION_PARAGRAPHS = 400
SLUG = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """A stable file name for a page. Same title, same file, every run."""
    folded = SLUG.sub("-", value.casefold()).strip("-")
    return folded[:60] or "seite"


# --------------------------------------------------------------------------- #
# The guide
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class GuideSection:
    title: str
    paragraphs: tuple[tuple[str, str, int], ...]


@dataclass(frozen=True, slots=True)
class Guide:
    title: str
    sections: tuple[GuideSection, ...]
    replaces: tuple[str, ...]
    struck: int

    @property
    def paragraph_count(self) -> int:
        return sum(len(section.paragraphs) for section in self.sections)


def compose_guide(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    *,
    title: str = "Leitfaden",
    scope: str = "normalized",
) -> Guide:
    """Fold a corpus into one guide, keeping every paragraph's source.

    Deduplication is what makes this replace documents rather than concatenate
    them: eight files repeating the same instruction become one paragraph, and
    the count of struck repeats is reported so nobody has to wonder what folding
    removed.
    """
    merged: MergedDocument = merge_sections(source_ids, texts)
    sections: list[GuideSection] = []
    struck = 0
    for section in merged.sections:
        outcome = deduplicate(section.paragraphs[:MAX_SECTION_PARAGRAPHS], scope=scope)
        struck += outcome.struck_count
        sections.append(
            GuideSection(
                title=section.title,
                paragraphs=tuple(
                    (item.text, item.anchor.source_id, item.anchor.line)
                    for item in outcome.kept
                ),
            )
        )
    return Guide(
        title=title,
        sections=tuple(sections),
        replaces=merged.source_ids,
        struck=struck,
    )


def guide_markdown(guide: Guide, labels: dict[str, str] | None = None) -> str:
    """Render the guide with a contents list and an anchor behind every line."""
    names = labels or {}
    lines = [f"# {guide.title}", ""]
    lines.append(
        "This guide is a compilation. Every paragraph below is a line from one of "
        "the documents it stands in for, with the source and line it came from. "
        "Nothing here was rewritten, so any paragraph can be checked against its "
        "original."
    )
    lines.extend(["", "## Was dieser Leitfaden zusammenfasst", ""])
    for source_id in guide.replaces:
        lines.append(f"- {names.get(source_id, source_id)}")
    if guide.struck:
        lines.extend(
            [
                "",
                f"{guide.struck} repeated paragraph(s) were folded into their first "
                "occurrence. Nothing else was removed.",
            ]
        )
    lines.extend(["", "## Inhalt", ""])
    for section in guide.sections:
        lines.append(f"- [{section.title}](#{slugify(section.title)})")
    for section in guide.sections:
        lines.extend(["", f"## {section.title}", ""])
        for text, source_id, line in section.paragraphs:
            lines.append(f"{text}")
            lines.append(f"  <sub>{names.get(source_id, source_id)}, line {line}</sub>")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# The wiki
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class WikiPage:
    slug: str
    title: str
    body: str
    source_id: str


def compose_wiki(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    *,
    labels: dict[str, str] | None = None,
    title: str = "Wiki",
) -> tuple[tuple[WikiPage, ...], str]:
    """One page per document plus an index, with nothing summarised.

    The page is the document, not a rendering of it: a wiki whose pages disagree
    with the files they came from is worse than no wiki at all.
    """
    names = labels or {}
    pages: list[WikiPage] = []
    used: set[str] = set()
    for source_id in source_ids[:MAX_PAGES]:
        text = texts.get(source_id)
        if text is None:
            continue
        display = names.get(source_id, source_id)
        slug = slugify(display)
        # Two documents can share a display name; a page silently overwriting
        # another would lose a source without saying so.
        suffix = 2
        while slug in used:
            slug = f"{slugify(display)}-{suffix}"
            suffix += 1
        used.add(slug)
        pages.append(
            WikiPage(
                slug=slug,
                title=display,
                body=(
                    f"# {display}\n\n"
                    f"<sub>Quelle: {source_id}. Der Inhalt unten ist unverändert "
                    "übernommen.</sub>\n\n"
                    + text.rstrip()
                    + "\n"
                ),
                source_id=source_id,
            )
        )
    index = [f"# {title}", ""]
    index.append(
        "Eine Seite je Dokument, nichts zusammengefasst. Jede Seite trägt den "
        "unveränderten Inhalt ihrer Quelle."
    )
    index.extend(["", "## Seiten", ""])
    for page in pages:
        index.append(f"- [{page.title}]({page.slug}.md)")
    return tuple(pages), "\n".join(index).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Pattern mining
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Pattern:
    text: str
    support: int
    sources: tuple[str, ...]
    anchor_total: int


@dataclass(frozen=True, slots=True)
class PatternReport:
    patterns: tuple[Pattern, ...]
    considered: int
    min_support: int
    notes: tuple[str, ...]


def mine_patterns(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    *,
    min_support: int = 3,
    focus_terms: tuple[str, ...] = (),
    partition_size: int = 40,
    max_patterns: int = 50,
) -> PatternReport:
    """Find lines that recur across a large set, with how often and from where.

    The staged aggregation does the work, which is the point: the anchors that
    survive it are what turn "this happens a lot" into "this happens a lot, here,
    here and here". A pattern below the support threshold is not reported at all
    rather than reported weakly, because a list where everything is a pattern is
    a list where nothing is.
    """
    if min_support < 2:
        raise ValueError("a pattern needs to occur at least twice to be one")
    statements: tuple[AnchoredStatement, ...] = statements_from_texts(
        source_ids, texts, focus_terms=focus_terms, min_words=3
    )
    outcome = aggregate_mapreduce(
        statements, budget=AggregationBudget(partition_size=partition_size, max_results=2000)
    )
    found = [
        Pattern(
            text=item.text,
            support=item.support,
            sources=tuple(dict.fromkeys(anchor.source_id for anchor in item.anchors)),
            anchor_total=item.anchor_total,
        )
        for item in outcome.results
        if item.support >= min_support
    ]
    found.sort(key=lambda item: (-item.support, item.text))
    notes = list(outcome.notes)
    if len(found) > max_patterns:
        notes.append(
            f"{len(found) - max_patterns} pattern(s) above the support threshold were "
            f"cut by the ceiling of {max_patterns}."
        )
    return PatternReport(
        patterns=tuple(found[:max_patterns]),
        considered=len(statements),
        min_support=min_support,
        notes=tuple(notes),
    )


def pattern_payload(
    report: PatternReport, labels: dict[str, str] | None = None
) -> dict[str, object]:
    names = labels or {}
    return {
        "schema": "nemofold.pattern-mining.v1",
        "considered_statements": report.considered,
        "min_support": report.min_support,
        "pattern_count": len(report.patterns),
        "patterns": [
            {
                "text": item.text,
                "support": item.support,
                "occurrences": item.anchor_total,
                "sources": [names.get(source, source) for source in item.sources],
            }
            for item in report.patterns
        ],
        "notes": list(report.notes),
        "reading_note": (
            "A recurring line is a finding about this corpus, not a rule about the "
            "world. That three thousand logs say the same sentence means the phrase "
            "is used, not that it is correct or that it should be."
        ),
    }
