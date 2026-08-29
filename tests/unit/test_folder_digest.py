from __future__ import annotations

from nemofold.contracts import SourceRecord
from nemofold.folder_digest import build_digest


def record(source_id: str, name: str, status: str) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        path=f"C:/private/{name}",
        display_name=name,
        sha256="a" * 64,
        mime_type="text/plain",
        extraction_status=status,
    )


def test_digest_summarizes_each_document_and_marks_delta_and_gap() -> None:
    records = (
        record("src_new", "new.txt", "new"),
        record("src_same", "same.txt", "unchanged"),
        record("src_gap", "locked.txt", "unreadable"),
    )
    texts = {
        "src_new": "First sentence. Second sentence! Third sentence? Fourth is omitted.",
        "src_same": "Stable document.",
    }

    digest = build_digest(records, texts, max_sentences=3)

    assert digest.cards[0].summary == "First sentence. Second sentence! Third sentence?"
    assert digest.changed_source_ids == ("src_new",)
    assert digest.gap_source_ids == ("src_gap",)
    assert "locked.txt — unavailable (unreadable)" in digest.markdown
    assert "Changes in this run" in digest.markdown
