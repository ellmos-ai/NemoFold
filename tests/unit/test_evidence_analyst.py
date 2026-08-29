from __future__ import annotations

import json

from nemofold.contracts import SourceRecord
from nemofold.document_index import DocumentIndex
from nemofold.evidence_analyst import build_context_receipts


def test_context_receipt_contains_only_artificial_ids_and_selected_chunks(tmp_path) -> None:
    index = DocumentIndex(tmp_path / "index.sqlite3")
    source = SourceRecord(
        source_id="src_policy",
        path=str(tmp_path / "private" / "real-name-policy.txt"),
        display_name="insurance/current.txt",
        sha256="a" * 64,
        mime_type="text/plain",
    )
    index.index_source(source, "Coverage begins on 1 April 2026. Deductible is 500 euros.")

    receipts = build_context_receipts(
        index,
        ("When does coverage begin?", "What is the deductible?"),
        hits_per_question=2,
    )
    payload = json.dumps([receipt.to_payload() for receipt in receipts], sort_keys=True)

    assert len(receipts) == 2
    assert "src_policy" in payload
    assert "real-name-policy" not in payload
    assert str(tmp_path) not in payload
    assert receipts[0].question == "When does coverage begin?"
    assert receipts[1].question == "What is the deductible?"
    index.close()
