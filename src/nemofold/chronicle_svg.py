"""Deterministic SVG for the Case Chronicle views.

Three properties this module is built for, in order.

**Deterministic bytes.** No timestamps, no randomness, no dictionary iteration
order, and every coordinate rounded to two decimals. The same input renders to
the same bytes, which is what lets a run ledger hash an image and mean it.

**Claim-safe.** Nothing is drawn that the data does not carry. An edge exists
only where a sentence stated it, a gap is drawn as a gap rather than filled in,
and an unknown time is a marked band rather than a plausible-looking point.

**Readable without colour.** Every distinction carries a text label as well as a
stroke style, and each figure has a legend plus a ``<desc>`` that says in words
what the picture shows. A finding nobody can read is not evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from xml.sax.saxutils import escape

SVG_HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n'
INK = "#0d2b33"
MUTED = "#5d7078"
ACCENT = "#1c7f86"
SIGNAL = "#c2552f"
PAPER = "#f6f2e6"
LINE = "#c9cfc7"
MAX_LABEL_CHARS = 28


def _round(value: float) -> str:
    """Two decimals, and never "-0.0"."""
    rendered = f"{value:.2f}"
    return "0.00" if rendered == "-0.00" else rendered


def _text(value: str, limit: int = MAX_LABEL_CHARS) -> str:
    collapsed = " ".join(str(value).split())
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1] + "…"
    return escape(collapsed)


@dataclass(frozen=True, slots=True)
class Figure:
    """A rendered figure and the sentence that describes it in words."""

    svg: str
    description: str

    def encode(self) -> bytes:
        return self.svg.encode("utf-8")


def _document(width: int, height: int, title: str, description: str, body: str) -> Figure:
    svg = (
        f'{SVG_HEADER}<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(description)}">\n'
        f"  <title>{escape(title)}</title>\n"
        f"  <desc>{escape(description)}</desc>\n"
        f'  <rect width="{width}" height="{height}" fill="{PAPER}"/>\n'
        f"{body}"
        "</svg>\n"
    )
    return Figure(svg=svg, description=description)


def _legend(entries: tuple[tuple[str, str], ...], x: float, y: float) -> str:
    """A legend where every entry is a word, not only a stroke."""
    parts = ['  <g class="legend" font-family="monospace" font-size="10">\n']
    for index, (mark, label) in enumerate(entries):
        offset = y + index * 14
        parts.append(
            f'    <text x="{_round(x)}" y="{_round(offset)}" fill="{MUTED}">'
            f"{escape(mark)} {escape(label)}</text>\n"
        )
    parts.append("  </g>\n")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# K5: the relation graph
# --------------------------------------------------------------------------- #


def relation_graph_svg(
    people: tuple[tuple[str, str], ...],
    edges: tuple[tuple[str, str, str, str], ...],
    *,
    width: int = 720,
    height: int = 520,
) -> Figure:
    """Draw people as nodes and stated relations as edges.

    ``people`` is (id, label) and ``edges`` is (subject, object, kind, quote).
    A node with no edge is still drawn: a person nobody linked to anyone is a
    finding, not an omission.
    """
    if not people:
        return _document(
            width, 160, "Relation graph",
            "No person was declared in the approved sources, so no graph was drawn.",
            f'  <text x="24" y="90" font-family="monospace" font-size="13" fill="{MUTED}">'
            "No declared person in these sources.</text>\n",
        )
    centre_x = width / 2
    centre_y = height / 2 - 10
    radius = min(width, height) / 2 - 110
    positions: dict[str, tuple[float, float]] = {}
    # Fixed angles from a fixed start: the layout is a function of the ordered
    # input, never of a random seed or a hash.
    step = 360.0 / len(people)
    for index, (entity_id, _) in enumerate(people):
        angle = math.radians(-90.0 + index * step)
        positions[entity_id] = (
            centre_x + radius * math.cos(angle),
            centre_y + radius * math.sin(angle),
        )

    body = [
        f'  <text x="24" y="32" font-family="monospace" font-size="12" fill="{INK}">'
        "RELATION GRAPH</text>\n"
    ]
    typed = 0
    for subject, target, kind, quote in edges:
        if subject not in positions or target not in positions:
            continue
        start = positions[subject]
        end = positions[target]
        is_typed = kind != "ko_nennung"
        typed += 1 if is_typed else 0
        dash = "" if is_typed else ' stroke-dasharray="5 4"'
        colour = ACCENT if is_typed else MUTED
        body.append(
            f'  <line x1="{_round(start[0])}" y1="{_round(start[1])}" '
            f'x2="{_round(end[0])}" y2="{_round(end[1])}" stroke="{colour}" '
            f'stroke-width="{"1.8" if is_typed else "1.1"}"{dash}>'
            f"<title>{_text(quote, 160)}</title></line>\n"
        )
        if is_typed:
            middle = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
            body.append(
                f'  <text x="{_round(middle[0])}" y="{_round(middle[1] - 4)}" '
                f'font-family="monospace" font-size="9" fill="{ACCENT}" '
                f'text-anchor="middle">{_text(kind, 18)}</text>\n'
            )
    for entity_id, label in people:
        x, y = positions[entity_id]
        body.append(
            f'  <circle cx="{_round(x)}" cy="{_round(y)}" r="7" fill="{PAPER}" '
            f'stroke="{INK}" stroke-width="1.6"/>\n'
            f'  <text x="{_round(x)}" y="{_round(y - 13)}" font-family="monospace" '
            f'font-size="10" fill="{INK}" text-anchor="middle">{_text(label)}</text>\n'
        )
    body.append(
        _legend(
            (
                ("———", "stated relation (typed, with quote)"),
                ("- - -", "named together in one sentence only"),
            ),
            24,
            height - 34,
        )
    )
    description = (
        f"Relation graph with {len(people)} people and {len(edges)} edges, of which "
        f"{typed} are typed relations stated in a sentence and {len(edges) - typed} "
        "record only that two people are named together. Every edge carries the "
        "sentence it came from."
    )
    return _document(width, height, "Relation graph", description, "".join(body))
