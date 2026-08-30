from __future__ import annotations

from nemofold.contracts import SourceRecord
from nemofold.document_index import DocumentIndex, chunk_text


def record(source_id: str, name: str, digest: str) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        path=f"C:/private/{name}",
        display_name=name,
        sha256=digest,
        mime_type="text/plain",
    )


def test_chunks_are_bounded_overlapping_and_stable() -> None:
    text = " ".join(f"word{i}" for i in range(80))

    first = chunk_text("src_a", text, max_chars=120, overlap_chars=20)
    second = chunk_text("src_a", text, max_chars=120, overlap_chars=20)

    assert first == second
    assert len(first) > 1
    assert all(len(chunk.text) <= 120 for chunk in first)
    assert first[0].chunk_id == "src_a:000000"
    assert set(first[0].text.split()) & set(first[1].text.split())


def test_chunker_makes_progress_for_a_single_very_long_token() -> None:
    chunks = chunk_text("src_long", "x" * 500, max_chars=120, overlap_chars=20)

    assert len(chunks) == 5
    assert all(0 < len(chunk.text) <= 120 for chunk in chunks)


def test_index_is_idempotent_and_replaces_changed_source(tmp_path) -> None:
    index = DocumentIndex(tmp_path / "index.sqlite3")
    first = record("src_policy", "policy.txt", "a" * 64)

    assert index.index_source(first, "The deductible is 500 euros.") == "indexed"
    assert index.index_source(first, "The deductible is 500 euros.") == "unchanged"
    hits = index.search("deductible", limit=5)
    assert hits[0].source_id == "src_policy"
    assert "500" in hits[0].text

    changed = record("src_policy", "policy.txt", "b" * 64)
    assert index.index_source(changed, "The premium is 70 euros.") == "updated"
    assert index.search("deductible", limit=5) == ()
    assert index.search('premium OR "unterminated', limit=5)[0].source_id == "src_policy"
    index.close()


def test_search_hit_preserves_original_character_and_line_location(tmp_path) -> None:
    text = "Heading\nCoverage begins on 1 April 2026.\nFinal note."
    source = record("src_lines", "nested/policy.txt", "c" * 64)
    index = DocumentIndex(tmp_path / "locations.sqlite3")
    index.index_source(source, text)

    hit = index.search("coverage begins", limit=1)[0]

    assert hit.line_start == 1
    assert hit.line_end == 3
    assert text[hit.char_start : hit.char_end].replace("\n", " ") == hit.text
    index.close()


def test_persistent_index_prunes_sources_missing_from_current_inventory(tmp_path) -> None:
    index = DocumentIndex(tmp_path / "persistent.sqlite3")
    first = record("src_first", "first.txt", "a" * 64)
    gone = record("src_gone", "gone.txt", "b" * 64)
    index.index_source(first, "Stable knowledge")
    index.index_source(gone, "Obsolete knowledge")

    removed = index.prune_sources({"src_first"})

    assert removed == ("src_gone",)
    assert index.search("obsolete") == ()
    assert index.search("stable")[0].source_id == "src_first"
    index.close()


def test_page_location_is_preserved_for_page_separated_extracted_text(tmp_path) -> None:
    source = record("src_pdf", "policy.pdf", "d" * 64)
    index = DocumentIndex(tmp_path / "pages.sqlite3")
    index.index_source(source, "First-page note.\fCoverage begins on page two.")

    hit = index.search("coverage begins", limit=1)[0]

    assert hit.page_start == 2
    assert hit.page_end == 2
    index.close()
