"""K4: when things happened, and where the sources simply do not say.

A timeline is the easiest place in this product to lie by accident. A document
says "irgendwann am Wochenende" and any tidy chart wants to put a dot somewhere;
once it does, a reader cannot tell the dot that was written down from the dot
that was placed to make the picture work. So an unparsable time is kept as
``unbestimmt`` and travels that way through the artifact and the drawing: it is
shown as the span it could be, never as a point it might not be.

Everything here is extractive. A time exists in the timeline because a sentence
or a declared field wrote it, and every event carries that sentence and its
anchor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .primitives import Anchor, anchored_sentences

PRECISION_MINUTE = "minute"
PRECISION_DAY = "day"
PRECISION_UNKNOWN = "unbestimmt"
PRECISIONS = (PRECISION_MINUTE, PRECISION_DAY, PRECISION_UNKNOWN)

KIND_POINT = "point"
KIND_INTERVAL = "interval"

MAX_EVENTS = 500
MAX_LABEL_CHARS = 200

# Words a document uses when it does not know. They are matched, not guessed at:
# an unrecognised time simply produces no event, while these produce an event
# that is explicitly undetermined.
UNCERTAIN_TERMS = (
    "irgendwann",
    "unbestimmt",
    "unklar",
    "nicht bekannt",
    "keine genaue",
    "zeitpunkt liegt mir nicht vor",
)

_DATE = re.compile(r"\b(?P<day>[0-3]?\d)\.(?P<month>[01]?\d)\.(?P<year>\d{4})\b")
_CLOCK = re.compile(r"\b(?P<hour>[0-2]?\d):(?P<minute>[0-5]\d)\b")
_ISO_DATE = re.compile(r"\b(?P<year>\d{4})-(?P<month>[01]\d)-(?P<day>[0-3]\d)\b")


@dataclass(frozen=True, slots=True)
class TimePoint:
    """A moment a source stated, or an explicit admission that it did not."""

    value: str | None
    precision: str
    raw: str

    @property
    def known(self) -> bool:
        return self.value is not None and self.precision != PRECISION_UNKNOWN


@dataclass(frozen=True, slots=True)
class Event:
    subject: str
    label: str
    start: TimePoint
    end: TimePoint | None
    kind: str
    anchor: Anchor
    quote: str

    @property
    def determined(self) -> bool:
        return self.start.known


@dataclass(frozen=True, slots=True)
class Timeline:
    events: tuple[Event, ...]
    notes: tuple[str, ...]

    @property
    def undetermined(self) -> tuple[Event, ...]:
        return tuple(event for event in self.events if not event.determined)

    def for_subject(self, subject: str) -> tuple[Event, ...]:
        return tuple(event for event in self.events if event.subject == subject)


def _iso(day: str, month: str, year: str, clock: tuple[str, str] | None) -> tuple[str, str]:
    date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    if clock is None:
        return date, PRECISION_DAY
    return f"{date}T{int(clock[0]):02d}:{int(clock[1]):02d}", PRECISION_MINUTE


def parse_times(text: str) -> tuple[TimePoint, ...]:
    """Read every stated time out of one piece of text, in the order written.

    A clock time only becomes a minute-precise point when a date stands with it.
    A bare "21:30" without a date says the hour, not the day, and inventing the
    day from a neighbouring sentence is exactly the guess this module refuses.
    """
    points: list[TimePoint] = []
    for match in _DATE.finditer(text):
        tail = text[match.end():match.end() + 24]
        clock = _CLOCK.search(tail)
        head = text[max(0, match.start() - 24):match.start()]
        if clock is None:
            clock = _CLOCK.search(head)
        value, precision = _iso(
            match.group("day"),
            match.group("month"),
            match.group("year"),
            (clock.group("hour"), clock.group("minute")) if clock else None,
        )
        raw = match.group(0) if clock is None else f"{match.group(0)} {clock.group(0)}"
        points.append(TimePoint(value=value, precision=precision, raw=raw))
    for match in _ISO_DATE.finditer(text):
        value, precision = _iso(
            match.group("day"), match.group("month"), match.group("year"), None
        )
        points.append(TimePoint(value=value, precision=precision, raw=match.group(0)))
    if points:
        return tuple(points)
    folded = text.casefold()
    for term in UNCERTAIN_TERMS:
        if term in folded:
            return (TimePoint(value=None, precision=PRECISION_UNKNOWN, raw=term),)
    return ()


# A statement document speaks in the first person, and the person speaking is
# declared in its header rather than repeated in every sentence. These markers
# are read off the text; they are not an inference about who "probably" means
# what.
FIRST_PERSON = (" ich ", "ich ", " mir", " mich", " mein", "meine ")


def _first_person(sentence: str) -> bool:
    padded = f" {sentence.casefold()} "
    return any(marker in padded for marker in FIRST_PERSON)


def _subject_of(
    sentence: str, mentions: dict[str, tuple[str, ...]], declared: str = ""
) -> str:
    """Whose event this is: the one person named, or the declared speaker.

    Naming two people makes a sentence ambiguous, and an ambiguous event is left
    unattributed rather than assigned to whichever name came first. A sentence
    that names nobody is attributed only when it is written in the first person
    and the document declares who is speaking.
    """
    found = [
        entity_id
        for entity_id, forms in mentions.items()
        if any(form.casefold() in sentence.casefold() for form in forms)
    ]
    if len(found) == 1:
        return found[0]
    if not found and declared and _first_person(sentence):
        return declared
    return ""


def speakers_of(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    mentions: dict[str, tuple[str, ...]],
    *,
    field: str = "Person",
) -> dict[str, str]:
    """Which declared person a document speaks for, read from its header field."""
    pattern = re.compile(rf"^\s*{re.escape(field)}\s*:\s*(?P<value>\S.*?)\s*$", re.IGNORECASE)
    speakers: dict[str, str] = {}
    for source_id in source_ids:
        text = texts.get(source_id)
        if text is None:
            continue
        for raw in text.splitlines():
            match = pattern.match(raw)
            if match is None:
                continue
            value = match.group("value").strip().casefold()
            for entity_id, forms in mentions.items():
                if any(form.casefold() == value for form in forms):
                    speakers[source_id] = entity_id
                    break
            break
    return speakers


def extract_events(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    *,
    mentions: dict[str, tuple[str, ...]] | None = None,
    max_events: int = MAX_EVENTS,
) -> Timeline:
    """Lift every sentence that states a time into an anchored event.

    A sentence stating two times becomes one interval; a sentence stating one
    becomes a point; a sentence admitting it does not know becomes an
    undetermined event rather than being dropped, because "the sources do not
    say when" is a finding a reader needs to see.
    """
    known = mentions or {}
    speakers = speakers_of(source_ids, texts, known)
    events: list[Event] = []
    notes: list[str] = []
    for source_id in source_ids:
        text = texts.get(source_id)
        if text is None:
            continue
        declared = speakers.get(source_id, "")
        for sentence in anchored_sentences(text):
            points = parse_times(sentence.text)
            if not points:
                continue
            if len(events) >= max_events:
                notes.append(
                    f"the event ceiling of {max_events} was reached; later sentences "
                    "were not read as events."
                )
                return Timeline(events=tuple(events), notes=tuple(notes))
            anchor = Anchor(source_id=source_id, line=sentence.line)
            start = points[0]
            end = points[1] if len(points) > 1 else None
            events.append(
                Event(
                    subject=_subject_of(sentence.text, known, declared),
                    label=sentence.text[:MAX_LABEL_CHARS],
                    start=start,
                    end=end,
                    kind=KIND_INTERVAL if end is not None else KIND_POINT,
                    anchor=anchor,
                    quote=sentence.text[:MAX_LABEL_CHARS],
                )
            )
    undetermined = sum(1 for event in events if not event.determined)
    if undetermined:
        notes.append(
            f"{undetermined} event(s) state a time the sources leave undetermined. "
            "They are kept as undetermined rather than placed at a guessed moment."
        )
    return Timeline(events=tuple(events), notes=tuple(notes))


def extract_coverage(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    *,
    start_field: str = "Deckung ab",
    end_field: str = "Deckung bis",
    label_field: str = "Tarif",
    holder_field: str = "Versicherungsnehmer",
) -> Timeline:
    """Read declared coverage intervals out of contract documents.

    Only the declared fields are read. A contract that names no end date yields
    an interval with an open end, which is what the paper says; filling it in
    with "probably a year" would be the model deciding when somebody was covered.
    """
    events: list[Event] = []
    notes: list[str] = []
    fields = (start_field, end_field, label_field, holder_field)
    pattern = {
        name: re.compile(rf"^\s*{re.escape(name)}\s*:\s*(?P<value>\S.*?)\s*$", re.IGNORECASE)
        for name in fields
    }
    for source_id in source_ids:
        text = texts.get(source_id)
        if text is None:
            continue
        values: dict[str, tuple[str, int]] = {}
        for number, raw in enumerate(text.splitlines(), start=1):
            for name in fields:
                match = pattern[name].match(raw)
                if match is not None and name not in values:
                    values[name] = (match.group("value").strip(), number)
        if start_field not in values:
            continue
        start_points = parse_times(values[start_field][0])
        if not start_points:
            notes.append(
                f"{source_id}: '{values[start_field][0]}' is not a readable date, so no "
                "coverage interval was derived from it."
            )
            continue
        end_points = parse_times(values[end_field][0]) if end_field in values else ()
        label = values.get(label_field, ("Deckung", 0))[0]
        holder = values.get(holder_field, ("", 0))[0]
        events.append(
            Event(
                subject=holder,
                label=label,
                start=start_points[0],
                end=end_points[0] if end_points else None,
                kind=KIND_INTERVAL,
                anchor=Anchor(source_id=source_id, line=values[start_field][1]),
                quote=f"{start_field}: {values[start_field][0]}"
                + (f" · {end_field}: {values[end_field][0]}" if end_field in values else ""),
            )
        )
    events.sort(key=lambda item: (item.start.value or "", item.anchor.source_id))
    if not events:
        notes.append("No document declared a coverage start, so no interval was drawn.")
    return Timeline(events=tuple(events), notes=tuple(notes))


def timeline_payload(timeline: Timeline, *, title: str) -> dict[str, object]:
    return {
        "schema": "nemofold.timeline.v1",
        "title": title,
        "event_count": len(timeline.events),
        "undetermined_count": len(timeline.undetermined),
        "events": [
            {
                "subject": event.subject,
                "label": event.label,
                "kind": event.kind,
                "start": event.start.value,
                "start_precision": event.start.precision,
                "start_raw": event.start.raw,
                "end": event.end.value if event.end else None,
                "end_precision": event.end.precision if event.end else None,
                "determined": event.determined,
                "source_id": event.anchor.source_id,
                "line": event.anchor.line,
                "quote": event.quote,
            }
            for event in timeline.events
        ],
        "notes": list(timeline.notes),
        "honesty_note": (
            "A time the sources do not state is carried as undetermined. It is never "
            "placed at a guessed moment to make the chart look complete."
        ),
    }


@dataclass(frozen=True, slots=True)
class CostItem:
    """A recurring or irregular cost declaration extracted from contract sources."""

    contract: str
    amount_raw: str
    amount: float | None
    cadence_raw: str
    cadence: str
    category: str
    due_date: TimePoint
    anchor: Anchor
    quote: str

    @property
    def determined(self) -> bool:
        return self.due_date.known


@dataclass(frozen=True, slots=True)
class CostTimeline:
    """Extracted cost items, timeline events and honesty notes."""

    items: tuple[CostItem, ...]
    timeline: Timeline
    notes: tuple[str, ...]


def _parse_amount(raw: str) -> float | None:
    cleaned = raw.replace("€", "").replace("EUR", "").replace("Euro", "").strip()
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)", cleaned)
    if not match:
        return None
    val_str = match.group(1).replace(",", ".")
    try:
        return float(val_str)
    except ValueError:
        return None


def _normalize_cadence(raw: str) -> tuple[str, str]:
    lower = raw.lower().strip()
    if any(term in lower for term in ("monat", "mtl", "monthly")):
        return "monthly", "recurring"
    if any(term in lower for term in ("quartal", "vierteljähr", "quarterly")):
        return "quarterly", "recurring"
    if any(term in lower for term in ("halbjahr", "semiannual")):
        return "semiannual", "recurring"
    if any(term in lower for term in ("jähr", "annual", "yearly", "jhrl")):
        return "annual", "special_effect"
    if any(term in lower for term in ("zweijähr", "biennial")):
        return "biennial", "special_effect"
    return "irregular", "special_effect"


def extract_costs(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    *,
    contract_field: str = "Vertrag",
    amount_field: str = "Betrag",
    cadence_field: str = "Turnus",
    due_date_field: str = "Nächste Fälligkeit",
    category_field: str = "Kategorie",
) -> CostTimeline:
    """Extract recurring and irregular cost items from declared document fields."""
    items: list[CostItem] = []
    events: list[Event] = []
    notes: list[str] = []
    fields = (contract_field, amount_field, cadence_field, due_date_field, category_field)
    pattern = {
        name: re.compile(rf"^\s*{re.escape(name)}\s*:\s*(?P<value>\S.*?)\s*$", re.IGNORECASE)
        for name in fields
    }

    for source_id in source_ids:
        text = texts.get(source_id)
        if text is None:
            continue
        current_block: dict[str, tuple[str, int]] = {}

        def _flush_block(block: dict[str, tuple[str, int]], src_id: str) -> None:
            if not block or contract_field not in block:
                return
            contract, c_line = block[contract_field]
            amount_raw = block.get(amount_field, ("", c_line))[0]
            amount = _parse_amount(amount_raw)
            cadence_raw = block.get(cadence_field, ("monatlich", c_line))[0]
            cadence_norm, default_cat = _normalize_cadence(cadence_raw)

            category_raw = block.get(category_field, ("", c_line))[0]
            if "wiederkehrend" in category_raw.lower():
                category = "recurring"
            elif any(
                t in category_raw.lower() for t in ("sondereffekt", "irregulär", "einmalig")
            ):
                category = "special_effect"
            else:
                category = default_cat

            due_raw = block.get(due_date_field, ("", c_line))[0]
            if due_raw and any(term in due_raw.lower() for term in UNCERTAIN_TERMS):
                due_point = TimePoint(value=None, precision=PRECISION_UNKNOWN, raw=due_raw)
            elif due_raw:
                parsed_times = parse_times(due_raw)
                if parsed_times and parsed_times[0].known:
                    due_point = parsed_times[0]
                else:
                    due_point = TimePoint(value=None, precision=PRECISION_UNKNOWN, raw=due_raw)
            else:
                due_point = TimePoint(value=None, precision=PRECISION_UNKNOWN, raw="unbekannt")

            quote_parts = [f"{contract_field}: {contract}"]
            if amount_raw:
                quote_parts.append(f"{amount_field}: {amount_raw}")
            if cadence_raw:
                quote_parts.append(f"{cadence_field}: {cadence_raw}")
            if due_raw:
                quote_parts.append(f"{due_date_field}: {due_raw}")
            quote = " · ".join(quote_parts)

            anchor = Anchor(source_id=src_id, line=c_line)
            cost_item = CostItem(
                contract=contract,
                amount_raw=amount_raw,
                amount=amount,
                cadence_raw=cadence_raw,
                cadence=cadence_norm,
                category=category,
                due_date=due_point,
                anchor=anchor,
                quote=quote,
            )
            items.append(cost_item)

            events.append(
                Event(
                    subject=f"{contract} ({cadence_raw})",
                    label=f"{contract}: {amount_raw}" if amount_raw else contract,
                    start=due_point,
                    end=None,
                    kind=KIND_POINT,
                    anchor=anchor,
                    quote=quote,
                )
            )

        for line_num, raw in enumerate(text.splitlines(), start=1):
            is_new_contract = pattern[contract_field].match(raw) is not None
            if is_new_contract and current_block:
                _flush_block(current_block, source_id)
                current_block = {}
            for name in fields:
                match = pattern[name].match(raw)
                if match is not None and name not in current_block:
                    current_block[name] = (match.group("value").strip(), line_num)

        if current_block:
            _flush_block(current_block, source_id)

    events.sort(key=lambda item: (item.start.value or "", item.anchor.source_id))
    if not items:
        notes.append("Keine Kostenpositionen in den geprüften Dokumenten gefunden.")
    timeline = Timeline(events=tuple(events), notes=tuple(notes))
    return CostTimeline(items=tuple(items), timeline=timeline, notes=tuple(notes))


def cost_timeline_payload(
    cost_timeline: CostTimeline,
    *,
    title: str,
    forecast_month: str | None = None,
    projected_recurring_total: float = 0.0,
    projected_special_effects_total: float = 0.0,
    undetermined_items: tuple[CostItem, ...] = (),
) -> dict[str, object]:
    return {
        "schema": "nemofold.cost-timeline.v1",
        "title": title,
        "item_count": len(cost_timeline.items),
        "undetermined_count": len(undetermined_items),
        "forecast_month": forecast_month,
        "projected_total": round(projected_recurring_total + projected_special_effects_total, 2),
        "projected_recurring_total": round(projected_recurring_total, 2),
        "projected_special_effects_total": round(projected_special_effects_total, 2),
        "items": [
            {
                "contract": item.contract,
                "amount": item.amount,
                "amount_raw": item.amount_raw,
                "cadence": item.cadence,
                "cadence_raw": item.cadence_raw,
                "category": item.category,
                "due_date": item.due_date.value,
                "determined": item.determined,
                "source_id": item.anchor.source_id,
                "line": item.anchor.line,
                "quote": item.quote,
            }
            for item in cost_timeline.items
        ],
        "undetermined_items": [
            {
                "contract": item.contract,
                "amount": item.amount,
                "amount_raw": item.amount_raw,
                "source_id": item.anchor.source_id,
                "line": item.anchor.line,
                "quote": item.quote,
                "note": "Unbekannte Fälligkeit; nicht in exakte Prognosen eingerechnet",
            }
            for item in undetermined_items
        ],
        "notes": list(cost_timeline.notes),
        "honesty_note": (
            "Unbekannte Fälligkeiten werden nicht als exakte Prognosen dargestellt. "
            "Wiederkehrende Kosten und erwartbare Sondereffekte werden getrennt mit Zeitraum "
            "und Quelle ausgewiesen."
        ),
    }

