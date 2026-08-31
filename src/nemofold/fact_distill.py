"""Distil extractive facts from a corpus and strike duplicates visibly.

Every statement is a sentence lifted verbatim from an approved source, so a
"fact" here is always quotable. Duplicates are removed from the findings but
never from the record: each struck occurrence keeps its own source and line in
an appendix, because a deduplication a reader cannot audit is indistinguishable
from a deletion.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

DEDUPE_SCOPES = frozenset({"exact", "normalized"})
MIN_FACT_WORDS = 4
MAX_FACT_CHARS = 400
MAX_FACTS_PER_SOURCE = 200
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
# A German ordinal ends a fragment with one or two digits and a period
# ("am 1." + "April 2026."), and splitting there would cut a fact in half so the
# halves escape deduplication and stop working as a quote. A four-digit year
# ("2026.") is a real sentence end, so the digit count is what separates them -
# a plain "period after a digit" rule gets the year wrong.
# Known limit: abbreviations such as "z. B." still split.
ORDINAL_TAIL = re.compile(r"(?:^|\D)\d{1,2}\.$")
PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
WHITESPACE = re.compile(r"\s+")


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


def _fingerprint(statement: str, scope: str) -> str:
    collapsed = WHITESPACE.sub(" ", statement).strip()
    if scope == "exact":
        return collapsed
    # "normalized" folds case, punctuation and accents so the same sentence
    # written twice with different typography collapses into one finding.
    folded = unicodedata.normalize("NFKD", collapsed.casefold())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return WHITESPACE.sub(" ", PUNCTUATION.sub(" ", folded)).strip()


def _sentences(text: str) -> tuple[tuple[int, str], ...]:
    """Yield (line number, sentence) pairs, keeping the anchor to the source."""
    results: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        merged: list[str] = []
        for fragment in SENTENCE_SPLIT.split(stripped):
            candidate = fragment.strip()
            if not candidate:
                continue
            if merged and ORDINAL_TAIL.search(merged[-1]):
                merged[-1] = f"{merged[-1]} {candidate}"
                continue
            merged.append(candidate)
        results.extend((number, sentence[:MAX_FACT_CHARS]) for sentence in merged)
    return tuple(results)


def _is_fact(sentence: str, focus_terms: tuple[str, ...]) -> bool:
    if len(sentence.split()) < MIN_FACT_WORDS:
        return False
    if not focus_terms:
        return True
    haystack = sentence.casefold()
    return any(term.casefold() in haystack for term in focus_terms)


def distil_facts(
    sources: tuple[str, ...],
    texts: dict[str, str],
    *,
    dedupe_scope: str = "normalized",
    focus_terms: tuple[str, ...] = (),
    max_facts_per_source: int = MAX_FACTS_PER_SOURCE,
) -> DistillResult:
    if dedupe_scope not in DEDUPE_SCOPES:
        raise ValueError("dedupe_scope must be exact or normalized")
    kept: dict[str, Fact] = {}
    facts: list[Fact] = []
    struck: list[StruckDuplicate] = []
    considered = 0
    for source_id in sources:
        text = texts.get(source_id)
        if text is None:
            continue
        taken = 0
        for line, sentence in _sentences(text):
            if taken >= max_facts_per_source:
                break
            if not _is_fact(sentence, focus_terms):
                continue
            considered += 1
            taken += 1
            key = _fingerprint(sentence, dedupe_scope)
            if not key:
                continue
            first = kept.get(key)
            if first is None:
                fact = Fact(statement=sentence, source_id=source_id, line=line)
                kept[key] = fact
                facts.append(fact)
                continue
            struck.append(
                StruckDuplicate(
                    statement=sentence,
                    kept_source_id=first.source_id,
                    kept_line=first.line,
                    duplicate_source_id=source_id,
                    duplicate_line=line,
                )
            )
    return DistillResult(
        facts=tuple(facts),
        struck=tuple(struck),
        dedupe_scope=dedupe_scope,
        considered=considered,
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
