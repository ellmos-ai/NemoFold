from __future__ import annotations

from pathlib import Path

import pytest

from nemofold.corroboration import (
    SUPPORT_CORROBORATED,
    SUPPORT_SELF,
    states_presence,
    weave_alibis,
    weave_payload,
    within,
)
from nemofold.entity_relation import build_entity_graph
from nemofold.timeline import (
    PRECISION_DAY,
    PRECISION_MINUTE,
    PRECISION_UNKNOWN,
    TimePoint,
    extract_coverage,
    extract_events,
    parse_times,
    timeline_payload,
)

CASE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "synthetic-case"
PLACES = ("Uferstraße", "Kiosk", "Werkstatt", "Betriebshof", "zu Hause", "Revier Nord")


def _case() -> tuple[tuple[str, ...], dict[str, str]]:
    paths = sorted(CASE_ROOT.glob("*.md"))
    return tuple(path.stem for path in paths), {
        path.stem: path.read_text(encoding="utf-8") for path in paths
    }


def _mentions() -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    graph = build_entity_graph(*_case())
    return (
        {item.entity_id: (item.canonical, *item.aliases) for item in graph.entities},
        graph.identity_map,
    )


# --------------------------------------------------------------------------- #
# K4: times that are stated, and times that are not
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "value", "precision"),
    [
        ("Am 14.03.2026 geschah es.", "2026-03-14", PRECISION_DAY),
        ("13.03.2026 17:00 angenommen", "2026-03-13T17:00", PRECISION_MINUTE),
        ("Am Samstag, 14.03.2026, gegen 21:30 Uhr", "2026-03-14T21:30", PRECISION_MINUTE),
        ("Rechnung vom 2026-04-02", "2026-04-02", PRECISION_DAY),
    ],
)
def test_a_stated_time_is_read_as_stated(text, value, precision) -> None:
    points = parse_times(text)

    assert points[0].value == value
    assert points[0].precision == precision


def test_a_bare_clock_time_without_a_date_is_not_invented_into_one() -> None:
    assert parse_times("Er kam um 21:30 Uhr an.") == ()


@pytest.mark.parametrize(
    "text",
    ["Das war irgendwann am Wochenende.", "Ein genauer Zeitpunkt liegt mir nicht vor."],
)
def test_an_admitted_unknown_becomes_undetermined_rather_than_a_guess(text) -> None:
    points = parse_times(text)

    assert points[0].precision == PRECISION_UNKNOWN
    assert points[0].value is None


def test_the_case_timeline_keeps_its_undetermined_events_and_says_so() -> None:
    mentions, _ = _mentions()

    timeline = extract_events(*_case(), mentions=mentions)

    assert timeline.events
    undetermined = timeline.undetermined
    assert len(undetermined) == 2
    assert all(item.anchor.source_id == "notiz-ostwald" for item in undetermined)
    assert any("undetermined rather than placed at a guessed moment" in note
               for note in timeline.notes)
    payload = timeline_payload(timeline, title="Fall")
    assert payload["undetermined_count"] == 2
    assert all(event["start"] is None for event in payload["events"]
               if not event["determined"])


def test_a_statement_is_attributed_to_the_person_the_document_declares() -> None:
    mentions, names = _mentions()

    timeline = extract_events(*_case(), mentions=mentions)

    attributed = {
        names[event.subject]: event.start.value
        for event in timeline.events
        if event.subject and event.anchor.source_id.startswith("vernehmung")
    }
    assert attributed["Marek Halvorsen"] == "2026-03-14T21:30"
    assert attributed["Ines Brandt"] == "2026-03-14T21:30"
    # The report's own sentences name no single person and stay unattributed.
    report = [
        event for event in timeline.events
        if event.anchor.source_id == "chronologie-entwurf" and event.subject
    ]
    assert report == []


def test_coverage_reads_the_declared_intervals_of_the_contracts() -> None:
    coverage = extract_coverage(*_case())

    intervals = [
        (event.label, event.start.value, event.end.value if event.end else None)
        for event in coverage.events
    ]
    assert ("Teilkasko", "2026-01-01", "2026-12-31") in intervals
    assert ("Vollkasko", "2026-03-01", "2026-12-31") in intervals
    assert all(event.subject == "Tobias Lenz" for event in coverage.events)


def test_a_contract_without_a_readable_start_is_reported_not_invented() -> None:
    texts = {"police": "Policennummer: X-1\nDeckung ab: nach Absprache\nTarif: Voll"}

    coverage = extract_coverage(("police",), texts)

    assert coverage.events == ()
    assert "is not a readable date" in coverage.notes[0]


# --------------------------------------------------------------------------- #
# K6: one line, two lines, and the gaps
# --------------------------------------------------------------------------- #


def test_an_undetermined_time_never_corroborates_anything() -> None:
    known = TimePoint(value="2026-03-14T21:30", precision=PRECISION_MINUTE, raw="x")
    unknown = TimePoint(value=None, precision=PRECISION_UNKNOWN, raw="irgendwann")

    assert within(known, known, 90) is True
    assert within(known, unknown, 90) is False
    assert within(unknown, unknown, 10_000) is False


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Marek Halvorsen stand dort ebenfalls.", True),
        ("Ines Brandt ist die Nachbarin von Marek Halvorsen.", False),
        ("Tobias Lenz hat den Wagen abgeholt.", True),
    ],
)
def test_naming_somebody_is_not_the_same_as_placing_them(sentence, expected) -> None:
    assert states_presence(sentence) is expected


def test_the_case_has_exactly_one_corroborated_position() -> None:
    mentions, names = _mentions()

    weave = weave_alibis(*_case(), mentions, places=PLACES)

    corroborated = [
        names[item.position.subject]
        for item in weave.supported
        if item.level == SUPPORT_CORROBORATED
    ]
    assert corroborated == ["Marek Halvorsen"]
    confirmation = next(
        item for item in weave.supported if item.level == SUPPORT_CORROBORATED
    ).confirmations[0]
    # Two real sentences travel with it: who says he was there, and where that
    # source places itself.
    assert "stand dort ebenfalls" in confirmation.naming_quote
    assert "Uferstraße" in confirmation.context_quote
    assert confirmation.by_source == "vernehmung-brandt"


def test_a_person_only_confirming_themselves_stays_on_one_line() -> None:
    mentions, names = _mentions()

    weave = weave_alibis(*_case(), mentions, places=PLACES)

    lenz = [
        item for item in weave.supported
        if names[item.position.subject] == "Tobias Lenz"
    ]
    assert lenz and all(item.level == SUPPORT_SELF for item in lenz)
    reasons = {gap.subject: gap.reason for gap in weave.gaps}
    lenz_id = next(key for key, value in names.items() if value == "Tobias Lenz")
    assert "no other source places this person" in reasons[lenz_id]


def test_a_person_nobody_places_is_reported_as_a_gap() -> None:
    mentions, names = _mentions()

    weave = weave_alibis(*_case(), mentions, places=PLACES)

    gaps = {names[gap.subject] for gap in weave.gaps}
    assert "Sabine Kröger" in gaps
    assert "Marek Halvorsen" not in gaps
    assert any("reported as a gap, not left out" in note for note in weave.notes)


def test_without_a_place_vocabulary_nothing_is_confirmed_by_time_alone() -> None:
    mentions, _ = _mentions()

    weave = weave_alibis(*_case(), mentions, places=())

    assert weave.supported == ()
    assert "No place vocabulary was given" in weave.notes[0]
    assert "nowhere near each other" in weave.notes[0]


def test_the_payload_carries_both_sentences_and_its_own_limits() -> None:
    mentions, _ = _mentions()

    payload = weave_payload(
        weave_alibis(*_case(), mentions, places=PLACES), window="14.-15.03.2026"
    )

    assert payload["corroborated_count"] == 1
    assert payload["gap_count"] >= 1
    confirmed = next(
        item for item in payload["positions"] if item["support"] == SUPPORT_CORROBORATED
    )
    assert confirmed["confirmations"][0]["naming_quote"]
    assert confirmed["confirmations"][0]["context_quote"]
    assert "not proof of anything" in payload["reasoning_note"]
