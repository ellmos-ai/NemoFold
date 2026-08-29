from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .document_index import DocumentIndex, SearchHit


@dataclass(frozen=True, slots=True)
class ContextReceipt:
    question: str
    hits: tuple[SearchHit, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "chunks": [
                {
                    "chunk_id": hit.chunk_id,
                    "source_id": hit.source_id,
                    "text": hit.text,
                }
                for hit in self.hits
            ],
            "response_schema": "nemofold.claims.v1",
        }


def build_context_receipts(
    index: DocumentIndex,
    questions: Sequence[str],
    *,
    hits_per_question: int = 8,
) -> tuple[ContextReceipt, ...]:
    if not questions or any(not question.strip() for question in questions):
        raise ValueError("at least one non-empty question is required")
    return tuple(
        ContextReceipt(
            question=question,
            hits=index.search(question, limit=hits_per_question),
        )
        for question in questions
    )
