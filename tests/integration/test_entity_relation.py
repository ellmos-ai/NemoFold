from __future__ import annotations

from pathlib import Path

import pytest

from nemofold.entity_relation import (
    CO_MENTION,
    build_entity_graph,
    build_relations,
    declared_names,
    registry_payload,
    resolve_entities,
)
from nemofold.primitives import anchored_sentences, is_field_line

CASE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "synthetic-case"


def _case() -> tuple[tuple[str, ...], dict[str, str]]:
    paths = sorted(CASE_ROOT.glob("*.md"))
    return tuple(path.stem for path in paths), {
        path.stem: path.read_text(encoding="utf-8") for path in paths
    }


# --------------------------------------------------------------------------- #
# Sentences that know their line, and fields that are not prose
# --------------------------------------------------------------------------- #


def test_a_name_that_wraps_onto_the_next_line_is_still_one_sentence() -> None:
    text = "Befragt wurden Marek Halvorsen, Ines Brandt und Nadja\nPflüger. Ende."

    sentences = anchored_sentences(text)

    assert sentences[0].text.endswith("Nadja Pflüger.")
    assert sentences[0].line == 1
    assert sentences[1].text == "Ende."


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Versicherungsnehmer: Tobias Lenz", True),
        ("Deckung ab: 01.01.2026", True),
        ("Vier Personen wurden befragt: Marek Halvorsen und Ines Brandt.", False),
        ("Ein Satz ohne Doppelpunkt", False),
    ],
)
def test_a_field_line_is_told_apart_from_prose(line, expected) -> None:
    assert is_field_line(line) is expected


def test_two_header_fields_never_become_one_sentence() -> None:
    text = "Versicherungsnehmer: Tobias Lenz\nBetreuer: Robert Ostwald"

    sentences = anchored_sentences(text)

    # Joined, these two people would share a sentence neither appears in, and a
    # co-mention edge would claim a link the document never states.
    assert [item.text for item in sentences] == [
        "Versicherungsnehmer: Tobias Lenz",
        "Betreuer: Robert Ostwald",
    ]


# --------------------------------------------------------------------------- #
# People exist because a document declares them
# --------------------------------------------------------------------------- #


def test_the_registry_holds_every_declared_person_of_the_case() -> None:
    entities, notes = resolve_entities(*_case())

    names = {entity.canonical for entity in entities}
    assert names == {
        "Kommissar Anselm Wieduwilt",
        "Robert Ostwald",
        "Tobias Lenz",
        "Ines Brandt",
        "Marek Halvorsen",
        "Nadja Pflüger",
        "Sabine Kröger",
    }
    assert notes == ()
    # The wrapped mention in the report is found, which is why Nadja is in there
    # with more than her own interrogation as a source.
    nadja = next(item for item in entities if item.canonical == "Nadja Pflüger")
    assert "polizeibericht-2026-03-16" in nadja.source_ids


def test_a_title_is_stripped_for_matching_and_kept_in_the_name() -> None:
    source_ids, texts = _case()

    entities, _ = resolve_entities(source_ids, texts)

    officer = next(item for item in entities if "Wieduwilt" in item.canonical)
    assert officer.canonical.startswith("Kommissar")
    assert sorted(officer.declared_as) == ["Bearbeitung", "Sachbearbeiter"]


def test_a_company_sharing_a_surname_does_not_become_a_mention() -> None:
    texts = {"akte": "Person: Nadja Pflüger\nDie Werkstatt Pflüger und Sohn hat geschlossen."}

    entities, _ = resolve_entities(("akte",), texts)

    nadja = entities[0]
    # Surname matching is off by default, so the workshop is not read as her.
    assert all("Werkstatt" not in mention.quote for mention in nadja.mentions)


def test_surname_matching_can_be_asked_for_explicitly() -> None:
    texts = {"akte": "Person: Nadja Pflüger\nFrau Pflüger kam um acht Uhr."}

    without, _ = resolve_entities(("akte",), texts)
    with_surnames, _ = resolve_entities(("akte",), texts, match_surnames=True)

    assert without[0].mention_count == 1
    assert with_surnames[0].mention_count == 2


def test_a_declared_name_that_never_appears_is_reported_not_hidden() -> None:
    texts = {"akte": "Person: Hilde Vandermolen"}

    entities, notes = resolve_entities(("akte",), texts, known_names=("Jan Ostermeier",))

    assert [item.canonical for item in entities] == ["Hilde Vandermolen"]
    assert "1 declared name(s) were never matched" in notes[0]


def test_only_the_declared_fields_seed_names() -> None:
    texts = {"akte": "Person: Ines Brandt\nStraße: Uferstraße Nord"}

    found = declared_names(("akte",), texts)

    assert found == (("Ines Brandt", "Person"),)


# --------------------------------------------------------------------------- #
# Edges exist because a sentence says so
# --------------------------------------------------------------------------- #


def test_every_edge_carries_the_sentence_that_states_it() -> None:
    graph = build_entity_graph(*_case())

    assert graph.relations
    for relation in graph.relations:
        assert relation.quote.strip()
        assert relation.anchor.source_id
        assert relation.anchor.line > 0
        subject = graph.by_id(relation.subject)
        target = graph.by_id(relation.object)
        assert subject is not None and target is not None


def test_a_typed_edge_needs_a_declared_relation_term() -> None:
    graph = build_entity_graph(*_case())

    typed = {(item.subject, item.object, item.kind) for item in graph.relations if item.typed}
    names = graph.identity_map
    readable = {(names[a], names[b], kind) for a, b, kind in typed}
    assert ("Robert Ostwald", "Tobias Lenz", "betreuung") in readable
    assert ("Ines Brandt", "Marek Halvorsen", "nachbarschaft") in readable
    assert ("Tobias Lenz", "Nadja Pflüger", "übergabe") in readable


def test_being_named_together_is_labelled_as_exactly_that() -> None:
    graph = build_entity_graph(*_case())

    co_mentions = [item for item in graph.relations if item.kind == CO_MENTION]
    assert co_mentions
    for relation in co_mentions:
        assert "befragt" in relation.quote or "," in relation.quote


def test_a_lone_person_in_a_sentence_produces_no_edge() -> None:
    texts = {"akte": "Person: Tobias Lenz\nTobias Lenz war allein zu Hause."}

    entities, _ = resolve_entities(("akte",), texts)
    relations, _ = build_relations(entities)

    assert relations == ()


def test_relations_are_deterministic_across_runs() -> None:
    first = build_entity_graph(*_case())
    second = build_entity_graph(*_case())

    assert [(item.subject, item.object, item.kind) for item in first.relations] == [
        (item.subject, item.object, item.kind) for item in second.relations
    ]


# --------------------------------------------------------------------------- #
# The pseudonymous form is actually pseudonymous
# --------------------------------------------------------------------------- #


def test_the_pseudonymous_registry_carries_no_name_and_no_quote() -> None:
    graph = build_entity_graph(*_case())

    payload = registry_payload(graph, pseudonymous=True)

    rendered = repr(payload)
    for name in graph.identity_map.values():
        assert name not in rendered
    assert payload["pseudonymous"] is True
    assert all("canonical" not in person for person in payload["people"])
    assert all("quote" not in edge for edge in payload["relations"])
    # It still says enough to be useful: who is linked to whom, and where.
    assert payload["relations"][0]["source_id"]


def test_the_identified_registry_keeps_names_quotes_and_the_map() -> None:
    graph = build_entity_graph(*_case())

    payload = registry_payload(graph, pseudonymous=False)

    assert payload["pseudonymous"] is False
    assert any(person.get("canonical") == "Tobias Lenz" for person in payload["people"])
    assert all(edge.get("quote") for edge in payload["relations"])
    assert graph.identity_map["PERSON_001"].endswith("Wieduwilt")
