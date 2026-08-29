from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .contracts import SourceRecord


@dataclass(frozen=True, slots=True)
class TextChunk:
    chunk_id: str
    source_id: str
    ordinal: int
    text: str


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: str
    source_id: str
    text: str
    rank: float


def chunk_text(
    source_id: str,
    text: str,
    *,
    max_chars: int = 2000,
    overlap_chars: int = 200,
) -> tuple[TextChunk, ...]:
    if max_chars < 32:
        raise ValueError("max_chars must be at least 32")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than max_chars")
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return ()

    chunks: list[TextChunk] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(" ", start + 1, end + 1)
            if boundary > start:
                end = boundary
        piece = normalized[start:end].strip()
        if piece:
            ordinal = len(chunks)
            chunks.append(
                TextChunk(
                    chunk_id=f"{source_id}:{ordinal:06d}",
                    source_id=source_id,
                    ordinal=ordinal,
                    text=piece,
                )
            )
        if end >= len(normalized):
            break
        next_start = max(0, end - overlap_chars)
        if next_start <= start:
            next_start = end
        while next_start > 0 and normalized[next_start - 1] != " ":
            next_start -= 1
        if next_start <= start:
            next_start = end
        start = next_start
    return tuple(chunks)


class DocumentIndex:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                sha256 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                text TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                chunk_id UNINDEXED,
                source_id UNINDEXED,
                text,
                tokenize = 'unicode61'
            );
            """
        )

    def close(self) -> None:
        self.connection.close()

    def index_source(self, source: SourceRecord, text: str) -> str:
        existing = self.connection.execute(
            "SELECT sha256 FROM sources WHERE source_id = ?", (source.source_id,)
        ).fetchone()
        if existing and existing[0] == source.sha256:
            return "unchanged"
        result = "updated" if existing else "indexed"
        chunks = chunk_text(source.source_id, text)
        with self.connection:
            self.connection.execute(
                "DELETE FROM chunks_fts WHERE source_id = ?", (source.source_id,)
            )
            self.connection.execute("DELETE FROM chunks WHERE source_id = ?", (source.source_id,))
            self.connection.execute(
                """
                INSERT INTO sources(source_id, display_name, sha256)
                VALUES (?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    sha256 = excluded.sha256
                """,
                (source.source_id, source.display_name, source.sha256),
            )
            self.connection.executemany(
                "INSERT INTO chunks(chunk_id, source_id, ordinal, text) VALUES (?, ?, ?, ?)",
                ((item.chunk_id, item.source_id, item.ordinal, item.text) for item in chunks),
            )
            self.connection.executemany(
                "INSERT INTO chunks_fts(chunk_id, source_id, text) VALUES (?, ?, ?)",
                ((item.chunk_id, item.source_id, item.text) for item in chunks),
            )
        return result

    @staticmethod
    def _safe_query(query: str) -> str:
        tokens = re.findall(r"[^\W_]{2,}", query, flags=re.UNICODE)
        return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)

    def search(self, query: str, *, limit: int = 10) -> tuple[SearchHit, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        safe_query = self._safe_query(query)
        if not safe_query:
            return ()
        rows = self.connection.execute(
            """
            SELECT chunk_id, source_id, text, bm25(chunks_fts) AS rank
            FROM chunks_fts
            WHERE chunks_fts MATCH ?
            ORDER BY rank, source_id, chunk_id
            LIMIT ?
            """,
            (safe_query, limit),
        ).fetchall()
        return tuple(SearchHit(*row) for row in rows)
