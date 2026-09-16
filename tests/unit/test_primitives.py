from __future__ import annotations

import pytest

from nemofold.primitives import (
    OWNER_RESOLVED,
    OWNER_UNSUPPORTED,
    Anchor,
    AnchoredStatement,
    FieldSpec,
    ascii_variant,
    deduplicate,
    extract_fields,
    fingerprint,
    merge_sections,
    resolve_owner,
    snapshot_delta,
    split_sentences,
    statements_from_texts,
    summarize,
)

REPORT_A = """# Befund
Patient: Lukas Geiger
Diagnose: Meniskus intakt.
Die Kontrolle erfolgt am 1. April 2026.
"""

REPORT_B = """# Befund
Patient: Lukas Geiger
Diagnose: Meniskus gerissen.
Die Kontrolle erfolgt am 1. April 2026.
"""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Termin am 1. April 2026. Danach Ruhe.",
         ["Termin am 1. April 2026.", "Danach Ruhe."]),
        # A year ends a sentence; so does a date fragment whose tail only looks
        # like an ordinal.
        ("Das Jahr endet 2026. Danach mehr.", ["Das Jahr endet 2026.", "Danach mehr."]),
        ("Rechnung 2026-04. Der Betrag folgt.",
         ["Rechnung 2026-04.", "Der Betrag folgt."]),
    ],
    ids=["ordinal", "year", "date-fragment"],
)
def test_one_sentence_splitter_for_every_caller(text: str, expected: list[str]) -> None:
    assert list(split_sentences(text)) == expected


def test_summaries_are_bounded_and_sentence_aligned() -> None:
    one = summarize(REPORT_A, 1)
    two = summarize(REPORT_A, 2)

    assert one == "# Befund Patient: Lukas Geiger Diagnose: Meniskus intakt."
    # The second sentence keeps its ordinal intact instead of being cut at "1.".
    assert two == f"{one} Die Kontrolle erfolgt am 1. April 2026."
    assert summarize(REPORT_A, 2, max_chars=20) == two[:20]
    assert summarize("", 3) == ""


def test_umlaut_folding_is_derived_not_maintained() -> None:
    assert ascii_variant("Nächste Fälligkeit") == "Naechste Faelligkeit"
    assert FieldSpec("Prämie").labels() == ("Prämie", "Praemie")


def test_fingerprint_scopes_differ_as_declared() -> None:
    assert fingerprint("Die  Deckung gilt.", "exact") == "Die Deckung gilt."
    assert fingerprint("DIE DECKUNG GILT!", "normalized") == fingerprint(
        "die deckung gilt.", "normalized"
    )
    with pytest.raises(ValueError, match="exact or normalized"):
        fingerprint("x", "fuzzy")


def test_extract_fields_anchors_what_it_finds_and_leaves_the_rest_empty() -> None:
    rows, skipped = extract_fields(
        (("src_a", "a.txt"),),
        {"src_a": REPORT_A},
        (FieldSpec("Diagnose"), FieldSpec("Kontakt")),
    )

    assert skipped == ()
    values = {value.field: value for value in rows[0].values}
    assert values["Diagnose"].value == "Meniskus intakt."
    assert values["Diagnose"].anchor == Anchor("src_a", 3)
    assert values["Kontakt"].filled is False
    assert values["Kontakt"].anchor is None


def test_structured_field_quote_still_contains_a_cell_after_a_long_prior_cell() -> None:
    line = "Zeile 1 · Vormerkung: " + ("x" * 300) + " · Befund: Schilddrüse stabil"
    rows, skipped = extract_fields(
        (("src_table", "medizin.sqlite"),),
        {"src_table": "# Tabelle medizin\n\n" + line + "\n"},
        (FieldSpec("Befund"),),
    )

    assert skipped == ()
    finding = rows[0].values[0]
    assert finding.value == "Schilddrüse stabil"
    assert finding.anchor == Anchor("src_table", 3)
    assert "Befund: Schilddrüse stabil" in finding.quote


def test_structured_registry_limit_blocks_instead_of_silently_omitting_records() -> None:
    text = "# Tabelle medizin\n\n" + "\n".join(
        f"Zeile {number} · Befund: Schilddrüse {number}" for number in range(1, 502)
    )
    with pytest.raises(ValueError, match="field_rows_limit_exceeded"):
        extract_fields(
            (("src_table", "medizin.sqlite"),),
            {"src_table": text},
            (FieldSpec("Befund"),),
            max_rows=500,
        )


def test_plain_text_with_a_row_like_note_keeps_ordinary_field_lines() -> None:
    rows, skipped = extract_fields(
        (("src_text", "bericht.txt"),),
        {"src_text": "Befund: Schilddrüse stabil\nZeile 1 · Notiz: Tabellenfuß\n"},
        (FieldSpec("Befund"),),
    )

    assert skipped == ()
    assert len(rows) == 1
    assert rows[0].record_line is None
    assert rows[0].values[0].value == "Schilddrüse stabil"
    assert rows[0].values[0].anchor == Anchor("src_text", 1)


def test_merge_flags_a_structured_cell_against_a_text_finding_in_one_section() -> None:
    merged = merge_sections(
        ("src_sqlite", "src_text"),
        {
            "src_sqlite": "# Befunde\nZeile 1 · Befund: Schilddrüse stabil\n",
            "src_text": "# Befunde\nBefund: Schilddrüse auffällig\n",
        },
        structured_source_ids=frozenset({"src_sqlite"}),
    )

    assert len(merged.conflicts) == 1
    conflict = merged.conflicts[0]
    assert conflict.section == "Befunde"
    assert conflict.label == "befund"
    assert conflict.values == (
        ("Schilddrüse stabil", Anchor("src_sqlite", 2)),
        ("Schilddrüse auffällig", Anchor("src_text", 2)),
    )


def test_merge_preserves_late_cell_of_a_long_structured_topic_row() -> None:
    prior_cells = " · ".join(
        f"Spalte {number}: " + "x" * 240 for number in range(1, 5)
    )
    text = f"# Befunde\nZeile 1 · {prior_cells} · Befund: Schilddrüse stabil\n"

    merged = merge_sections(
        ("src_sqlite",), {"src_sqlite": text},
        structured_source_ids=frozenset({"src_sqlite"}),
    )

    paragraphs = merged.sections[0].paragraphs
    assert any("Befund: Schilddrüse stabil" in item.text for item in paragraphs)
    assert all(item.anchor == Anchor("src_sqlite", 2) for item in paragraphs)
    assert all(item.text in text.splitlines()[1] for item in paragraphs)


def test_merge_keeps_an_ordinary_text_row_like_note_as_one_verbatim_paragraph() -> None:
    text = "# Notizen\nZeile 1 · Alpha: a · Beta: b\n"

    merged = merge_sections(("src_text",), {"src_text": text})

    assert [item.text for item in merged.sections[0].paragraphs] == [
        "Zeile 1 · Alpha: a · Beta: b"
    ]


def test_deduplicate_keeps_the_first_and_records_every_strike() -> None:
    statements = (
        AnchoredStatement("Die Deckung gilt.", Anchor("src_a", 1)),
        AnchoredStatement("die  deckung gilt!", Anchor("src_b", 7)),
    )

    outcome = deduplicate(statements, scope="normalized")

    assert [item.text for item in outcome.kept] == ["Die Deckung gilt."]
    assert outcome.struck_count == 1
    assert outcome.struck[0].statement.anchor == Anchor("src_b", 7)
    assert outcome.struck[0].duplicate_of.anchor == Anchor("src_a", 1)

    exact = deduplicate(statements, scope="exact")
    assert exact.struck_count == 0


def test_merge_sections_surfaces_a_disagreement_as_a_conflict() -> None:
    merged = merge_sections(("src_a", "src_b"), {"src_a": REPORT_A, "src_b": REPORT_B})

    assert [section.title for section in merged.sections] == ["Befund"]
    conflict = next(item for item in merged.conflicts if item.label == "diagnose")
    assert {value for value, _ in conflict.values} == {
        "Meniskus intakt.",
        "Meniskus gerissen.",
    }
    # The patient line agrees in both, so it is not a conflict.
    assert "patient" not in {item.label for item in merged.conflicts}


def test_snapshot_delta_describes_only_the_named_new_sources(tmp_path) -> None:
    target = tmp_path / "neu.txt"
    target.write_text(REPORT_A, encoding="utf-8")
    records = (("src_a", "alt.txt", str(target)), ("src_b", "neu.txt", str(target)))

    entries, owner_status = snapshot_delta(records, {"src_b": REPORT_A}, ("src_b",))

    assert [entry.source_id for entry in entries] == ["src_b"]
    assert entries[0].size_bytes == target.stat().st_size
    assert entries[0].summary.startswith("# Befund")
    assert owner_status in {OWNER_RESOLVED, OWNER_UNSUPPORTED}


def test_owner_is_named_or_the_reason_is(tmp_path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")
    owner, status = resolve_owner(target)
    assert status in {OWNER_RESOLVED, OWNER_UNSUPPORTED}
    assert (owner is None) == (status != OWNER_RESOLVED)


def test_primitives_compose_into_a_case_no_workflow_ships(tmp_path) -> None:
    """The point of D-032: chain primitives for a case nobody wrote a workflow for.

    Here: merge two reports, then deduplicate the merged paragraphs, keeping the
    conflict the merge found. No shipped workflow does this combination.
    """
    merged = merge_sections(("src_a", "src_b"), {"src_a": REPORT_A, "src_b": REPORT_B})
    paragraphs = tuple(
        paragraph for section in merged.sections for paragraph in section.paragraphs
    )

    outcome = deduplicate(paragraphs, scope="normalized")

    # The identical patient and follow-up lines fold; the differing diagnosis stays.
    kept = [item.text for item in outcome.kept]
    assert "Diagnose: Meniskus intakt." in kept
    assert "Diagnose: Meniskus gerissen." in kept
    assert kept.count("Patient: Lukas Geiger") == 1
    assert outcome.struck_count == 2
    assert all(item.statement.anchor.source_id == "src_b" for item in outcome.struck)
    # And the merge's own conflict is still available next to the folded text.
    assert len(merged.conflicts) == 1


def test_statements_carry_their_anchor_from_text_to_dedupe() -> None:
    statements = statements_from_texts(("src_a",), {"src_a": REPORT_A}, min_words=3)

    assert all(isinstance(item.anchor, Anchor) for item in statements)
    assert any("Kontrolle erfolgt am 1. April 2026." in item.text for item in statements)
