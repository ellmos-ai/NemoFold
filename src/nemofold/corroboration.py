"""K6: how well a stated position is actually supported, and where nothing is.

The distinction this module exists for is one line versus two. A person saying
where they were is one line. Another source placing that same person at the same
place inside the same time window is a second line. They look similar in a
report and mean entirely different things, so they are never merged here.

The reasoning is deliberately shallow and says so. A confirmation is recorded
when a *different* source says the person was present - a naming sentence alone
does not count, or being somebody's neighbour would read as an alibi - and that
source also places itself at the same place within the tolerance window. Not
because that proves anything, but because it is what the documents contain.
Both sentences travel with the confirmation so a reader can judge the inference
instead of inheriting it.

A gap is its own output rather than an absence in a list. "No source places this
person anywhere in the window" is a finding, and a view that simply leaves them
out would hide the most interesting thing on the page.
"""

from __future__ import annotations

from dataclasses import dataclass

from .primitives import Anchor, anchored_sentences
from .timeline import PRECISION_UNKNOWN, TimePoint, parse_times, speakers_of

SUPPORT_SELF = "selbstauskunft"
SUPPORT_CORROBORATED = "fremdbestaetigt"
SUPPORT_LEVELS = (SUPPORT_SELF, SUPPORT_CORROBORATED)

# A sentence that merely names somebody is not a sighting. "Ines Brandt ist die
# Nachbarin von Marek Halvorsen" names her without saying she was anywhere, and
# counting it as a confirmation would inflate exactly the number this module is
# meant to keep honest. A naming sentence must carry a presence marker, and the
# vocabulary is declared rather than inferred.
PRESENCE_TERMS = (
    "stand", "standen", "war", "waren", "sah", "sahen", "traf", "trafen",
    "ebenfalls", "dort", "dabei", "anwesend", "kam", "kamen", "ging", "gingen",
    "abgeholt", "übergab", "vorbei",
)

MAX_POSITIONS = 400
MAX_QUOTE_CHARS = 240
DEFAULT_TOLERANCE_MINUTES = 90


@dataclass(frozen=True, slots=True)
class Position:
    """A stated whereabouts: who, where, when, and the sentence that says it."""

    subject: str
    place: str
    time: TimePoint
    anchor: Anchor
    quote: str
    self_reported: bool


@dataclass(frozen=True, slots=True)
class Confirmation:
    """A different source placing the same person at the same place and time."""

    by_source: str
    naming_quote: str
    naming_anchor: Anchor
    context_quote: str
    context_anchor: Anchor


@dataclass(frozen=True, slots=True)
class SupportedPosition:
    position: Position
    confirmations: tuple[Confirmation, ...]

    @property
    def level(self) -> str:
        return SUPPORT_CORROBORATED if self.confirmations else SUPPORT_SELF


@dataclass(frozen=True, slots=True)
class Gap:
    subject: str
    reason: str


@dataclass(frozen=True, slots=True)
class Weave:
    supported: tuple[SupportedPosition, ...]
    gaps: tuple[Gap, ...]
    notes: tuple[str, ...]

    @property
    def corroborated_count(self) -> int:
        return sum(1 for item in self.supported if item.level == SUPPORT_CORROBORATED)


def _minutes(value: str | None) -> int | None:
    """Minutes since epoch-ish, for a same-scale comparison of two stated times."""
    if not value:
        return None
    date, _, clock = value.partition("T")
    try:
        year, month, day = (int(part) for part in date.split("-"))
    except ValueError:
        return None
    total = ((year * 12 + month) * 31 + day) * 24 * 60
    if clock:
        hour, _, minute = clock.partition(":")
        try:
            total += int(hour) * 60 + int(minute)
        except ValueError:
            return None
    return total


def within(first: TimePoint, second: TimePoint, tolerance_minutes: int) -> bool:
    """True when two stated times are close enough to describe one occasion.

    An undetermined time is never close to anything. Treating "irgendwann" as
    matching would manufacture the corroboration this module exists to withhold.
    """
    if first.precision == PRECISION_UNKNOWN or second.precision == PRECISION_UNKNOWN:
        return False
    left, right = _minutes(first.value), _minutes(second.value)
    if left is None or right is None:
        return False
    return abs(left - right) <= tolerance_minutes


def states_presence(sentence: str, presence_terms: tuple[str, ...] = PRESENCE_TERMS) -> bool:
    """True when a sentence says somebody was somewhere, not merely who they are.

    Punctuation is flattened first, or a marker at the end of a sentence
    ("... hat den Wagen abgeholt.") would be missed and the sighting lost.
    """
    flattened = "".join(
        " " if character in ".,;:!?()\"'" else character for character in sentence.casefold()
    )
    padded = f" {flattened} "
    return any(f" {term} " in padded for term in presence_terms)


def _place_in(sentence: str, places: tuple[str, ...]) -> str:
    folded = sentence.casefold()
    for place in places:
        if place.casefold() in folded:
            return place
    return ""


def collect_positions(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    mentions: dict[str, tuple[str, ...]],
    *,
    places: tuple[str, ...],
    max_positions: int = MAX_POSITIONS,
) -> tuple[tuple[Position, ...], tuple[str, ...]]:
    """Find every sentence that puts a named or speaking person at a place and time."""
    speakers = speakers_of(source_ids, texts, mentions)
    positions: list[Position] = []
    notes: list[str] = []
    if not places:
        notes.append(
            "No place vocabulary was given, so nothing could be compared by place. "
            "Positions and confirmations are therefore not derived at all rather "
            "than derived from time alone, which would confirm people who were "
            "nowhere near each other."
        )
        return (), tuple(notes)
    for source_id in source_ids:
        text = texts.get(source_id)
        if text is None:
            continue
        speaker = speakers.get(source_id, "")
        for sentence in anchored_sentences(text):
            place = _place_in(sentence.text, places)
            if not place:
                continue
            times = parse_times(sentence.text)
            if not times:
                continue
            named = [
                entity_id
                for entity_id, forms in mentions.items()
                if any(form.casefold() in sentence.text.casefold() for form in forms)
            ]
            subject = named[0] if len(named) == 1 else (speaker if not named else "")
            if not subject:
                continue
            if len(positions) >= max_positions:
                notes.append(
                    f"the position ceiling of {max_positions} was reached; later "
                    "sentences were not read as positions."
                )
                break
            positions.append(
                Position(
                    subject=subject,
                    place=place,
                    time=times[0],
                    anchor=Anchor(source_id=source_id, line=sentence.line),
                    quote=sentence.text[:MAX_QUOTE_CHARS],
                    self_reported=bool(named == [] and speaker == subject),
                )
            )
    return tuple(positions), tuple(notes)


def weave_alibis(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    mentions: dict[str, tuple[str, ...]],
    *,
    places: tuple[str, ...],
    tolerance_minutes: int = DEFAULT_TOLERANCE_MINUTES,
    presence_terms: tuple[str, ...] = PRESENCE_TERMS,
) -> Weave:
    """Rate each stated position, and name everyone the sources never place."""
    positions, notes = collect_positions(
        source_ids, texts, mentions, places=places
    )
    all_notes = list(notes)
    speakers = speakers_of(source_ids, texts, mentions)
    # What each document says about itself: where and when it places its own
    # narrator. That context is what makes a naming sentence usable.
    context: dict[str, list[Position]] = {}
    for position in positions:
        if position.self_reported:
            context.setdefault(position.anchor.source_id, []).append(position)

    supported: list[SupportedPosition] = []
    for position in positions:
        if not position.self_reported:
            continue
        confirmations: list[Confirmation] = []
        for source_id in source_ids:
            if source_id == position.anchor.source_id:
                continue
            text = texts.get(source_id)
            if text is None or speakers.get(source_id) == position.subject:
                continue
            forms = mentions.get(position.subject, ())
            for sentence in anchored_sentences(text):
                if not any(form.casefold() in sentence.text.casefold() for form in forms):
                    continue
                if not states_presence(sentence.text, presence_terms):
                    continue
                for anchor_position in context.get(source_id, []):
                    if anchor_position.place != position.place:
                        continue
                    if not within(anchor_position.time, position.time, tolerance_minutes):
                        continue
                    confirmations.append(
                        Confirmation(
                            by_source=source_id,
                            naming_quote=sentence.text[:MAX_QUOTE_CHARS],
                            naming_anchor=Anchor(source_id=source_id, line=sentence.line),
                            context_quote=anchor_position.quote,
                            context_anchor=anchor_position.anchor,
                        )
                    )
                    break
        supported.append(
            SupportedPosition(position=position, confirmations=tuple(confirmations))
        )

    placed = {item.position.subject for item in supported if item.confirmations}
    stated = {item.position.subject for item in supported}
    gaps = [
        Gap(
            subject=subject,
            reason=(
                "states a position, but no other source places this person there at "
                "that time"
                if subject in stated
                else "no source places this person anywhere in the window"
            ),
        )
        for subject in sorted(mentions)
        if subject not in placed
    ]
    if gaps:
        all_notes.append(
            f"{len(gaps)} person(s) have no position confirmed by another source. "
            "That is reported as a gap, not left out of the picture."
        )
    supported.sort(key=lambda item: (item.position.subject, item.position.anchor.line))
    return Weave(supported=tuple(supported), gaps=tuple(gaps), notes=tuple(all_notes))


def weave_payload(weave: Weave, *, window: str) -> dict[str, object]:
    return {
        "schema": "nemofold.alibi-weave.v1",
        "window": window,
        "position_count": len(weave.supported),
        "corroborated_count": weave.corroborated_count,
        "gap_count": len(weave.gaps),
        "positions": [
            {
                "subject": item.position.subject,
                "place": item.position.place,
                "time": item.position.time.value,
                "time_precision": item.position.time.precision,
                "support": item.level,
                "source_id": item.position.anchor.source_id,
                "line": item.position.anchor.line,
                "quote": item.position.quote,
                "confirmations": [
                    {
                        "by_source": confirmation.by_source,
                        "naming_quote": confirmation.naming_quote,
                        "naming_line": confirmation.naming_anchor.line,
                        "context_quote": confirmation.context_quote,
                        "context_line": confirmation.context_anchor.line,
                    }
                    for confirmation in item.confirmations
                ],
            }
            for item in weave.supported
        ],
        "gaps": [{"subject": gap.subject, "reason": gap.reason} for gap in weave.gaps],
        "notes": list(weave.notes),
        "reasoning_note": (
            "A confirmation means another source says this person was present and "
            "places itself at the same place inside the tolerance window. A sentence "
            "that only names somebody does not count. That is what the documents "
            "contain, not proof of anything. Both sentences are shown so the inference "
            "can be judged rather than inherited."
        ),
    }
