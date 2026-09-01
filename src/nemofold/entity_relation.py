"""K5: who appears in a corpus, and which links between them are actually written down.

Two rules decide everything in this module.

**A person exists because a document declares them.** Names are seeded from
labelled fields a caller names - Person, Versicherungsnehmer, Sachbearbeiter -
and then matched across the corpus. There is deliberately no "looks like a name"
heuristic: in German prose a capitalised pair is as likely to be a street, a
company or a district, and a registry that quietly invents people is worse than
one that misses them. What it misses, it can be told about.

**An edge exists because a sentence says so.** Every relation carries the exact
sentence and its anchor. Co-mention says only that two people are named in one
sentence and is labelled as exactly that; a typed edge additionally requires a
declared relation term. An edge without a quote is not written - which is the
whole reason a graph like this can be shown to somebody at all.

Pseudonyms follow the anonymizer's convention (``<PERSON_001>``) and are assigned
in first-appearance order over a deterministic scan. That number therefore
encodes scan position, not identity or importance, and the mapping back to real
names is written as its own local artifact so an export can leave it behind.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .primitives import Anchor, anchored_sentences, ascii_variant

MAX_ENTITIES = 200
MAX_MENTIONS_PER_ENTITY = 200
MAX_RELATIONS = 400
MAX_QUOTE_CHARS = 300

# Titles a document may put in front of a declared name. They are stripped for
# matching but kept in the canonical spelling, because "Kommissar" is part of how
# that person appears in the file.
NAME_TITLES = (
    "kommissar", "kommissarin", "hauptkommissar", "dr.", "dr", "prof.", "prof",
    "herr", "frau", "rechtsanwalt", "rechtsanwältin",
)

DEFAULT_NAME_FIELDS = (
    "Person",
    "Versicherungsnehmer",
    "Sachbearbeiter",
    "Sachbearbeiterin",
    "Betreuer",
    "Betreuerin",
    "Halter",
    "Halterin",
    "Bearbeitung",
    "Kontakt",
    "Zeuge",
    "Zeugin",
)

# A typed edge needs one of these between two named people. The table is a
# default, not a truth: a caller working on another kind of corpus passes its own.
DEFAULT_RELATION_TERMS: dict[str, tuple[str, ...]] = {
    "nachbarschaft": ("nachbarin von", "nachbar von"),
    "betreuung": ("betreut",),
    "leitung": ("leitet",),
    "übergabe": ("übergab", "übergeben an"),
    "beauftragung": ("beauftragt", "beauftragte"),
    "vertretung": ("vertritt", "vertrat"),
}

CO_MENTION = "ko_nennung"

_LABELLED = re.compile(r"^\s*(?P<label>[^:#]{2,60}?)\s*:\s*(?P<value>\S.*?)\s*$")
_NAME_VALUE = re.compile(r"^[^\d,;]{3,80}$")


def _strip_titles(name: str) -> str:
    parts = name.split()
    while parts and parts[0].casefold().strip(".") in {
        item.strip(".") for item in NAME_TITLES
    }:
        parts = parts[1:]
    return " ".join(parts)


def _key(name: str) -> str:
    return " ".join(ascii_variant(_strip_titles(name)).casefold().split())


@dataclass(frozen=True, slots=True)
class Mention:
    """One place a declared person is named, with the sentence that names them."""

    entity_id: str
    surface: str
    anchor: Anchor
    quote: str


@dataclass(frozen=True, slots=True)
class Entity:
    entity_id: str
    canonical: str
    aliases: tuple[str, ...]
    declared_as: tuple[str, ...]
    mentions: tuple[Mention, ...]
    source_ids: tuple[str, ...]

    @property
    def mention_count(self) -> int:
        return len(self.mentions)


@dataclass(frozen=True, slots=True)
class Relation:
    """A link between two people that a sentence actually states."""

    subject: str
    object: str
    kind: str
    quote: str
    anchor: Anchor

    @property
    def typed(self) -> bool:
        return self.kind != CO_MENTION


@dataclass(frozen=True, slots=True)
class EntityGraph:
    entities: tuple[Entity, ...]
    relations: tuple[Relation, ...]
    notes: tuple[str, ...]

    def by_id(self, entity_id: str) -> Entity | None:
        return next((item for item in self.entities if item.entity_id == entity_id), None)

    @property
    def identity_map(self) -> dict[str, str]:
        """entity_id to real name. Local only; never part of a pseudonymous export."""
        return {item.entity_id: item.canonical for item in self.entities}


def declared_names(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    *,
    name_fields: tuple[str, ...] = DEFAULT_NAME_FIELDS,
) -> tuple[tuple[str, str], ...]:
    """Collect (name, field) pairs from the labelled lines a caller trusts."""
    wanted = {label.casefold() for label in name_fields}
    wanted |= {ascii_variant(label).casefold() for label in name_fields}
    found: list[tuple[str, str]] = []
    for source_id in source_ids:
        text = texts.get(source_id)
        if text is None:
            continue
        for raw in text.splitlines():
            match = _LABELLED.match(raw)
            if match is None:
                continue
            label = match.group("label").strip()
            if label.casefold() not in wanted and ascii_variant(label).casefold() not in wanted:
                continue
            value = match.group("value").strip()
            if not _NAME_VALUE.match(value) or len(value.split()) < 2:
                continue
            found.append((value, label))
    return tuple(found)


def _register(
    names: tuple[tuple[str, str], ...], extra: tuple[str, ...]
) -> tuple[dict[str, dict[str, object]], list[str]]:
    """Fold spellings of the same person together, keeping the fullest one."""
    registry: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for value, label in (*names, *((item, "given") for item in extra)):
        key = _key(value)
        if not key:
            continue
        if key not in registry:
            order.append(key)
            registry[key] = {"canonical": value, "spellings": [value], "fields": [label]}
            continue
        record = registry[key]
        spellings = record["spellings"]
        fields = record["fields"]
        assert isinstance(spellings, list) and isinstance(fields, list)
        if value not in spellings:
            spellings.append(value)
        if label not in fields:
            fields.append(label)
        if len(value) > len(str(record["canonical"])):
            record["canonical"] = value
    return registry, order


def resolve_entities(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    *,
    name_fields: tuple[str, ...] = DEFAULT_NAME_FIELDS,
    known_names: tuple[str, ...] = (),
    match_surnames: bool = False,
    max_entities: int = MAX_ENTITIES,
) -> tuple[tuple[Entity, ...], tuple[str, ...]]:
    """Resolve declared people and find every sentence that names them.

    ``match_surnames`` is off by default on purpose. A bare surname matches the
    workshop named after the family as readily as the person, and a mention the
    corpus does not contain is exactly the kind of invention this registry must
    not make.
    """
    declared = declared_names(source_ids, texts, name_fields=name_fields)
    registry, order = _register(declared, known_names)
    notes: list[str] = []
    if len(order) > max_entities:
        notes.append(
            f"{len(order) - max_entities} declared name(s) beyond the ceiling of "
            f"{max_entities} were not resolved."
        )
        order = order[:max_entities]

    patterns: dict[str, re.Pattern[str]] = {}
    for key in order:
        record = registry[key]
        spellings = record["spellings"]
        assert isinstance(spellings, list)
        forms = {str(item) for item in spellings}
        forms |= {_strip_titles(str(item)) for item in spellings}
        if match_surnames:
            forms |= {
                str(item).split()[-1] for item in spellings if len(str(item).split()) > 1
            }
        alternatives = sorted({form for form in forms if len(form) > 2}, key=len, reverse=True)
        patterns[key] = re.compile(
            "|".join(re.escape(form) for form in alternatives), re.IGNORECASE
        )

    mentions: dict[str, list[Mention]] = {key: [] for key in order}
    sources: dict[str, list[str]] = {key: [] for key in order}
    # First appearance in this deterministic scan decides the number, matching
    # the anonymizer's counter convention.
    numbering: dict[str, str] = {}
    for source_id in source_ids:
        text = texts.get(source_id)
        if text is None:
            continue
        # Sentences rather than lines: a surname that wrapped onto the next line
        # would otherwise match nothing and drop a person out of the registry
        # without a word.
        for sentence in anchored_sentences(text):
            for key in order:
                match = patterns[key].search(sentence.text)
                if match is None:
                    continue
                if key not in numbering:
                    numbering[key] = f"PERSON_{len(numbering) + 1:03d}"
                if len(mentions[key]) >= MAX_MENTIONS_PER_ENTITY:
                    continue
                mentions[key].append(
                    Mention(
                        entity_id=numbering[key],
                        surface=match.group(0),
                        anchor=Anchor(source_id=source_id, line=sentence.line),
                        quote=sentence.text[:MAX_QUOTE_CHARS],
                    )
                )
                if source_id not in sources[key]:
                    sources[key].append(source_id)

    entities: list[Entity] = []
    for key in sorted(numbering, key=lambda item: numbering[item]):
        record = registry[key]
        spellings = record["spellings"]
        fields = record["fields"]
        assert isinstance(spellings, list) and isinstance(fields, list)
        canonical = str(record["canonical"])
        entities.append(
            Entity(
                entity_id=numbering[key],
                canonical=canonical,
                aliases=tuple(
                    sorted({str(item) for item in spellings} - {canonical})
                ),
                declared_as=tuple(sorted(str(item) for item in fields)),
                mentions=tuple(mentions[key]),
                source_ids=tuple(sources[key]),
            )
        )
    unmentioned = [key for key in order if key not in numbering]
    if unmentioned:
        notes.append(
            f"{len(unmentioned)} declared name(s) were never matched in the text and "
            "are not in the registry."
        )
    return tuple(entities), tuple(notes)


def _relation_kind(sentence: str, terms: dict[str, tuple[str, ...]]) -> str | None:
    folded = sentence.casefold()
    for kind in sorted(terms):
        if any(term.casefold() in folded for term in terms[kind]):
            return kind
    return None


def build_relations(
    entities: tuple[Entity, ...],
    *,
    relation_terms: dict[str, tuple[str, ...]] | None = None,
    max_relations: int = MAX_RELATIONS,
) -> tuple[tuple[Relation, ...], tuple[str, ...]]:
    """Build edges from sentences that name two people. Never from inference.

    A sentence naming two people supports a co-mention and nothing more; calling
    that a relationship would be the graph inventing a claim. A declared relation
    term in the same sentence upgrades it to a typed edge, and the sentence
    travels with the edge either way.
    """
    terms = DEFAULT_RELATION_TERMS if relation_terms is None else relation_terms
    grouped: dict[tuple[str, int, str], list[str]] = {}
    for entity in entities:
        for mention in entity.mentions:
            key = (mention.anchor.source_id, mention.anchor.line, mention.quote)
            names = grouped.setdefault(key, [])
            if entity.entity_id not in names:
                names.append(entity.entity_id)

    relations: list[Relation] = []
    notes: list[str] = []
    for (source_id, line, quote), names in grouped.items():
        if len(names) < 2:
            continue
        kind = _relation_kind(quote, terms) or CO_MENTION
        anchor = Anchor(source_id=source_id, line=line)
        for index, subject in enumerate(names):
            for target in names[index + 1:]:
                if len(relations) >= max_relations:
                    notes.append(
                        f"the relation ceiling of {max_relations} was reached; later "
                        "sentences were not turned into edges."
                    )
                    return tuple(relations), tuple(notes)
                relations.append(
                    Relation(
                        subject=subject,
                        object=target,
                        kind=kind,
                        quote=quote,
                        anchor=anchor,
                    )
                )
    relations.sort(key=lambda item: (item.subject, item.object, item.kind,
                                     item.anchor.source_id, item.anchor.line))
    return tuple(relations), tuple(notes)


def build_entity_graph(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    *,
    name_fields: tuple[str, ...] = DEFAULT_NAME_FIELDS,
    known_names: tuple[str, ...] = (),
    match_surnames: bool = False,
    relation_terms: dict[str, tuple[str, ...]] | None = None,
) -> EntityGraph:
    entities, entity_notes = resolve_entities(
        source_ids,
        texts,
        name_fields=name_fields,
        known_names=known_names,
        match_surnames=match_surnames,
    )
    relations, relation_notes = build_relations(entities, relation_terms=relation_terms)
    return EntityGraph(
        entities=entities,
        relations=relations,
        notes=(*entity_notes, *relation_notes),
    )


def registry_payload(graph: EntityGraph, *, pseudonymous: bool) -> dict[str, object]:
    """Render the registry either with real names or with pseudonyms only.

    The pseudonymous form is what may be sent somewhere. It carries no canonical
    name, no alias and no surface form, because a "pseudonymous" export that
    still quotes the sentence a name appears in would be pseudonymous in name
    only. Re-identification happens locally, against the identity map.
    """
    people: list[dict[str, object]] = []
    for entity in graph.entities:
        record: dict[str, object] = {
            "entity_id": entity.entity_id,
            "declared_as": list(entity.declared_as),
            "mention_count": entity.mention_count,
            "source_ids": list(entity.source_ids),
        }
        if not pseudonymous:
            record["canonical"] = entity.canonical
            record["aliases"] = list(entity.aliases)
            record["mentions"] = [
                {
                    "surface": mention.surface,
                    "source_id": mention.anchor.source_id,
                    "line": mention.anchor.line,
                    "quote": mention.quote,
                }
                for mention in entity.mentions
            ]
        people.append(record)
    edges: list[dict[str, object]] = []
    for relation in graph.relations:
        edge: dict[str, object] = {
            "subject": relation.subject,
            "object": relation.object,
            "kind": relation.kind,
            "source_id": relation.anchor.source_id,
            "line": relation.anchor.line,
        }
        if not pseudonymous:
            edge["quote"] = relation.quote
        edges.append(edge)
    return {
        "schema": "nemofold.person-registry.v1",
        "pseudonymous": pseudonymous,
        "person_count": len(people),
        "relation_count": len(edges),
        "typed_relation_count": sum(1 for item in graph.relations if item.typed),
        "people": people,
        "relations": edges,
        "notes": list(graph.notes),
        "identity_note": (
            "Pseudonyms are numbered in the order the scan first met them, so the "
            "number reflects scan position, not identity or importance. The mapping "
            "back to real names stays local."
            if pseudonymous
            else "This form carries real names and belongs on this host only."
        ),
    }
