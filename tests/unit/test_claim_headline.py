from __future__ import annotations

from types import SimpleNamespace

from nemofold.application import _analysis_claim


def hit(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=text, source_id="src", chunk_id="c1", line_start=1, line_end=4,
        page_start=None, page_end=None,
    )


PASSAGE = (
    "SYNTHETISCHER FALL — FREI ERFUNDEN. Welche Angaben vorliegen, steht unten. "
    "# Werkstattbeleg Fahrzeug: VW Golf, Farbe blau Kennzeichen: B-TL 4471."
)


def test_the_headline_is_the_sentence_that_shares_a_word_with_the_question() -> None:
    claim = _analysis_claim(
        "Welche Farbe hatte der Wagen mit dem Kennzeichen B-TL 4471?",
        (hit(PASSAGE),),
        conflict_scan=False,
    )
    # Not the fiction notice, and not the sentence that only shares "Welche".
    assert claim.statement.endswith("Farbe blau Kennzeichen: B-TL 4471.")
    assert claim.evidence[0].quote == PASSAGE


def test_without_a_shared_word_the_first_sentence_remains_and_long_ones_are_cut() -> None:
    fallback = _analysis_claim("Zzz?", (hit(PASSAGE),), conflict_scan=False)
    long = _analysis_claim("Farbe?", (hit("Farbe " + "x" * 400 + "."),), conflict_scan=False)

    assert fallback.statement.endswith("SYNTHETISCHER FALL — FREI ERFUNDEN.")
    assert long.statement.endswith("…")
    assert len(long.statement.split("states: ", 1)[1]) == 240
