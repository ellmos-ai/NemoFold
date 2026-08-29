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
