"""Distil extractive facts from a corpus and strike duplicates visibly.

A thin contract over two shared primitives: statements_from_texts lifts quotable
sentences with their anchors, deduplicate folds the repeats. This module only
adds the workflow's own vocabulary and the appendix that keeps every struck
occurrence readable.
"""

from __future__ import annotations

from dataclasses import dataclass

from .primitives import (
    DEDUPE_SCOPES,
    deduplicate,
    statements_from_texts,
)

MIN_FACT_WORDS = 4
MAX_FACTS_PER_SOURCE = 200


@dataclass(frozen=True, slots=True)
class Fact:
    statement: str
    source_id: str
    line: int


@dataclass(frozen=True, slots=True)
class StruckDuplicate:
    statement: str
    kept_source_id: str
    kept_line: int
    duplicate_source_id: str
    duplicate_line: int


@dataclass(frozen=True, slots=True)
class DistillResult:
    facts: tuple[Fact, ...]
    struck: tuple[StruckDuplicate, ...]
    dedupe_scope: str
    considered: int

    @property
    def struck_count(self) -> int:
        return len(self.struck)


def distil_facts(
    sources: tuple[str, ...],
    texts: dict[str, str],
    *,
    dedupe_scope: str = "normalized",
    focus_terms: tuple[str, ...] = (),
    max_facts_per_source: int = MAX_FACTS_PER_SOURCE,
) -> DistillResult:
    """Compose: lift anchored statements, then fold the repeated ones."""
    if dedupe_scope not in DEDUPE_SCOPES:
        raise ValueError("dedupe_scope must be exact or normalized")
    statements = statements_from_texts(
        sources,
        texts,
        min_words=MIN_FACT_WORDS,
        focus_terms=focus_terms,
        max_per_source=max_facts_per_source,
    )
    outcome = deduplicate(statements, scope=dedupe_scope)
    return DistillResult(
        facts=tuple(
            Fact(
                statement=item.text,
                source_id=item.anchor.source_id,
                line=item.anchor.line,
            )
            for item in outcome.kept
        ),
        struck=tuple(
            StruckDuplicate(
                statement=item.statement.text,
                kept_source_id=item.duplicate_of.anchor.source_id,
                kept_line=item.duplicate_of.anchor.line,
                duplicate_source_id=item.statement.anchor.source_id,
                duplicate_line=item.statement.anchor.line,
            )
            for item in outcome.struck
        ),
        dedupe_scope=dedupe_scope,
        considered=len(statements),
    )


def struck_markdown(result: DistillResult) -> str:
    """Render the appendix that keeps every removed occurrence visible."""
    lines = [
        "# Struck duplicates",
        "",
        f"Deduplication scope: {result.dedupe_scope}.",
        f"{result.struck_count} occurrences were struck from the findings and are listed "
        "here with the statement they duplicate. Nothing was deleted from a source.",
        "",
    ]
    if not result.struck:
        lines.append("No duplicate statement was found in this corpus.")
        return "\n".join(lines) + "\n"
    for item in result.struck:
        lines.extend(
            [
                f"- {item.statement}",
                f"  - struck from {item.duplicate_source_id}, line {item.duplicate_line}",
                f"  - kept in {item.kept_source_id}, line {item.kept_line}",
            ]
        )
    return "\n".join(lines) + "\n"
