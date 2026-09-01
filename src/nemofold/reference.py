"""K2: checking a document against a reference grid, and saying what is missing.

This is the primitive behind "does this letter contain what such a letter should
contain". A reference is a declared list of items - a checklist somebody wrote,
not one this program inferred - and the check reports, per item, whether the
corpus answers it and where.

Three rules keep it honest.

**Present means quoted.** An item counts as answered only when a line was found,
and that line travels with the result. A checkmark without a quote is an opinion.

**Missing is a finding, not a failure.** The absent items are the output people
actually came for, so they are listed with the reference text that was looked
for, rather than being counted and discarded.

**It compares, it does not judge.** A reference check says an item is present or
absent. It does not say the document is correct, valid, sufficient or lawful,
and every report repeats that. Whether a missing item matters is a question for
somebody qualified to answer it, and this program is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .primitives import Anchor, anchored_sentences, ascii_variant

MAX_ITEMS = 100
MAX_LABEL_CHARS = 120
MAX_QUOTE_CHARS = 300

# Shipped reference grids. They are starting points a person edits, not
# authoritative lists: a checklist that claims completeness about somebody's
# legal situation would be exactly the claim this module refuses.
REFERENCE_GRIDS: dict[str, tuple[dict[str, Any], ...]] = {
    "bescheid_formal": (
        {"key": "absender", "label": "Absender", "terms": ["Absender", "Behörde", "Amt"]},
        {"key": "datum", "label": "Datum", "terms": ["Datum", "vom"]},
        {"key": "aktenzeichen", "label": "Aktenzeichen",
         "terms": ["Aktenzeichen", "Geschäftszeichen", "AZ"]},
        {"key": "empfaenger", "label": "Empfänger", "terms": ["Empfänger", "An"]},
        {"key": "entscheidung", "label": "Entscheidung",
         "terms": ["Entscheidung", "Bescheid", "wird bewilligt", "wird abgelehnt"]},
        {"key": "begruendung", "label": "Begründung", "terms": ["Begründung", "Weil", "da "]},
        {"key": "rechtsbehelf", "label": "Rechtsbehelfsbelehrung",
         "terms": ["Rechtsbehelf", "Widerspruch", "Klage"]},
        {"key": "unterschrift", "label": "Unterschrift oder Zeichnung",
         "terms": ["Unterschrift", "gezeichnet", "i. A.", "im Auftrag"]},
    ),
    "vertrag_kern": (
        {"key": "parteien", "label": "Vertragsparteien", "terms": ["Zwischen", "Parteien"]},
        {"key": "gegenstand", "label": "Vertragsgegenstand",
         "terms": ["Gegenstand", "Leistung"]},
        {"key": "laufzeit", "label": "Laufzeit", "terms": ["Laufzeit", "Beginn", "Ende"]},
        {"key": "verguetung", "label": "Vergütung",
         "terms": ["Vergütung", "Beitrag", "Entgelt", "Preis"]},
        {"key": "kuendigung", "label": "Kündigung", "terms": ["Kündigung", "Kündigungsfrist"]},
    ),
    "voyage_design_review": (
        {"key": "zweck", "label": "Zweck ist benannt", "terms": ["Zweck", "Ziel", "Frage"]},
        {"key": "quellen", "label": "Quellen sind benannt",
         "terms": ["Quelle", "Ordner", "Korpus"]},
        {"key": "ergebnis", "label": "Erwartetes Ergebnis",
         "terms": ["Ergebnis", "Bericht", "Ausgabe", "Artefakt"]},
        {"key": "grenzen", "label": "Grenzen sind benannt",
         "terms": ["Grenze", "nicht", "ausgenommen", "offen"]},
    ),
}

NO_JUDGEMENT = (
    "This check reports which declared items the sources answer and which they do "
    "not. It does not say the document is correct, valid, sufficient or lawful, "
    "and it is not advice. Whether a missing item matters is a question for "
    "somebody qualified to answer it."
)

_LABELLED = re.compile(r"^\s*(?P<label>[^:#]{2,60}?)\s*:\s*(?P<value>\S.*?)\s*$")


@dataclass(frozen=True, slots=True)
class ReferenceItem:
    """One line of a declared checklist."""

    key: str
    label: str
    terms: tuple[str, ...]
    required: bool = True

    def all_terms(self) -> tuple[str, ...]:
        declared = (self.label, *self.terms)
        return tuple(
            dict.fromkeys(
                (*declared, *(ascii_variant(item) for item in declared))
            )
        )


@dataclass(frozen=True, slots=True)
class ItemFinding:
    item: ReferenceItem
    present: bool
    anchor: Anchor | None = None
    quote: str = ""
    matched_term: str = ""


@dataclass(frozen=True, slots=True)
class ReferenceReport:
    grid: str
    findings: tuple[ItemFinding, ...]

    @property
    def present(self) -> tuple[ItemFinding, ...]:
        return tuple(item for item in self.findings if item.present)

    @property
    def missing(self) -> tuple[ItemFinding, ...]:
        return tuple(item for item in self.findings if not item.present)

    @property
    def missing_required(self) -> tuple[ItemFinding, ...]:
        return tuple(item for item in self.missing if item.item.required)

    @property
    def complete(self) -> bool:
        return not self.missing_required


def validate_items(value: Any) -> tuple[ReferenceItem, ...]:
    """Read a declared checklist, refusing one that says nothing to look for."""
    if not isinstance(value, list) or not value:
        raise ValueError("a reference grid needs a non-empty list of items")
    if len(value) > MAX_ITEMS:
        raise ValueError(f"a reference grid may not exceed {MAX_ITEMS} items")
    items: list[ReferenceItem] = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) - {"key", "label", "terms", "required"}:
            raise ValueError("an item holds only key, label, terms and required")
        key = str(entry.get("key", "")).strip()
        label = str(entry.get("label", "")).strip()
        if not key or not label:
            raise ValueError("every item needs a key and a label")
        if len(label) > MAX_LABEL_CHARS:
            raise ValueError(f"a label may not exceed {MAX_LABEL_CHARS} characters")
        terms = entry.get("terms") or [label]
        if not isinstance(terms, list) or any(not isinstance(item, str) for item in terms):
            raise ValueError("terms must be a list of strings")
        required = entry.get("required", True)
        if not isinstance(required, bool):
            raise ValueError("required must be a boolean")
        items.append(
            ReferenceItem(
                key=key,
                label=label,
                terms=tuple(item.strip() for item in terms if item.strip()),
                required=required,
            )
        )
    return tuple(items)


def grid_named(name: str) -> tuple[ReferenceItem, ...]:
    """One of the shipped grids, or a plain refusal naming the ones that exist."""
    grid = REFERENCE_GRIDS.get(name)
    if grid is None:
        raise ValueError(
            f"unknown reference grid: {name}. Available: {', '.join(sorted(REFERENCE_GRIDS))}"
        )
    return validate_items([dict(item) for item in grid])


def validate_against_reference(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    items: tuple[ReferenceItem, ...],
    *,
    grid: str = "custom",
) -> ReferenceReport:
    """Check each declared item against the corpus and quote what answered it.

    A labelled line wins over a loose mention: "Aktenzeichen: 12/34" is the
    document answering the item, while the same word inside a sentence may be
    the document merely talking about it. Both count as present, but the
    labelled line is the one quoted when there is a choice.
    """
    findings: list[ItemFinding] = []
    for item in items:
        best: ItemFinding | None = None
        for source_id in source_ids:
            text = texts.get(source_id)
            if text is None:
                continue
            for sentence in anchored_sentences(text):
                labelled = _LABELLED.match(sentence.text)
                for term in item.all_terms():
                    if not term or term.casefold() not in sentence.text.casefold():
                        continue
                    candidate = ItemFinding(
                        item=item,
                        present=True,
                        anchor=Anchor(source_id=source_id, line=sentence.line),
                        quote=sentence.text[:MAX_QUOTE_CHARS],
                        matched_term=term,
                    )
                    is_label = (
                        labelled is not None
                        and term.casefold() in labelled.group("label").casefold()
                    )
                    if best is None or (is_label and not _is_label_hit(best)):
                        best = candidate
                    break
                if best is not None and _is_label_hit(best):
                    break
            if best is not None and _is_label_hit(best):
                break
        findings.append(best or ItemFinding(item=item, present=False))
    return ReferenceReport(grid=grid, findings=tuple(findings))


def _is_label_hit(finding: ItemFinding) -> bool:
    if not finding.present or not finding.quote:
        return False
    match = _LABELLED.match(finding.quote)
    return match is not None and finding.matched_term.casefold() in (
        match.group("label").casefold()
    )


def reference_payload(report: ReferenceReport) -> dict[str, object]:
    return {
        "schema": "nemofold.reference-check.v1",
        "grid": report.grid,
        "item_count": len(report.findings),
        "present_count": len(report.present),
        "missing_count": len(report.missing),
        "complete": report.complete,
        "items": [
            {
                "key": finding.item.key,
                "label": finding.item.label,
                "required": finding.item.required,
                "present": finding.present,
                "matched_term": finding.matched_term,
                "source_id": finding.anchor.source_id if finding.anchor else None,
                "line": finding.anchor.line if finding.anchor else None,
                "quote": finding.quote,
            }
            for finding in report.findings
        ],
        "missing": [
            {
                "key": finding.item.key,
                "label": finding.item.label,
                "required": finding.item.required,
                "looked_for": list(finding.item.terms),
            }
            for finding in report.missing
        ],
        "no_judgement_note": NO_JUDGEMENT,
    }
