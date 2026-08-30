from __future__ import annotations

import re
import sqlite3
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

from .contracts import SourceRecord


@dataclass(frozen=True, slots=True)
class TextChunk:
    chunk_id: str
    source_id: str
    ordinal: int
    text: str
    char_start: int
    char_end: int
    line_start: int
    line_end: int
    page_start: int | None
    page_end: int | None


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: str
    source_id: str
    text: str
    rank: float
    char_start: int = 0
    char_end: int = 0
    line_start: int = 1
    line_end: int = 1
    page_start: int | None = None
    page_end: int | None = None


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
    if "\f" in text:
        paged_chunks: list[TextChunk] = []
        character_offset = 0
        line_offset = 0
        for page_number, page_text in enumerate(text.split("\f"), start=1):
            for item in chunk_text(
                source_id,
                page_text,
                max_chars=max_chars,
                overlap_chars=overlap_chars,
            ):
                ordinal = len(paged_chunks)
                paged_chunks.append(
                    TextChunk(
                        chunk_id=f"{source_id}:{ordinal:06d}",
                        source_id=source_id,
                        ordinal=ordinal,
                        text=item.text,
                        char_start=item.char_start + character_offset,
                        char_end=item.char_end + character_offset,
                        line_start=item.line_start + line_offset,
                        line_end=item.line_end + line_offset,
                        page_start=page_number,
                        page_end=page_number,
                    )
                )
            character_offset += len(page_text) + 1
            line_offset += page_text.count("\n")
        return tuple(paged_chunks)
    tokens = tuple(re.finditer(r"\S+", text))
    normalized = " ".join(match.group(0) for match in tokens)
    if not normalized:
        return ()

    normalized_starts: list[int] = []
    normalized_ends: list[int] = []
    cursor = 0
    for match in tokens:
        normalized_starts.append(cursor)
        cursor += len(match.group(0))
        normalized_ends.append(cursor)
        cursor += 1
    newline_positions = [index for index, character in enumerate(text) if character == "\n"]
    page_break_positions = [index for index, character in enumerate(text) if character == "\f"]

    def original_bounds(normalized_start: int, normalized_end: int) -> tuple[int, int]:
        start_index = max(0, bisect_right(normalized_starts, normalized_start) - 1)
        if normalized_start >= normalized_ends[start_index] and start_index + 1 < len(tokens):
            start_index += 1
        end_position = max(normalized_start, normalized_end - 1)
        end_index = max(0, bisect_right(normalized_starts, end_position) - 1)
        if end_position >= normalized_ends[end_index] and end_index + 1 < len(tokens):
            end_index += 1
        start_match = tokens[start_index]
        end_match = tokens[end_index]
        original_start = start_match.start() + max(
            0, normalized_start - normalized_starts[start_index]
        )
        original_end = end_match.start() + min(
            len(end_match.group(0)),
            end_position - normalized_starts[end_index] + 1,
        )
        return original_start, original_end

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
            piece_start = start
            piece_end = start + len(piece)
            original_start, original_end = original_bounds(piece_start, piece_end)
            chunks.append(
                TextChunk(
                    chunk_id=f"{source_id}:{ordinal:06d}",
                    source_id=source_id,
                    ordinal=ordinal,
                    text=piece,
                    char_start=original_start,
                    char_end=original_end,
                    line_start=bisect_right(newline_positions, original_start) + 1,
                    line_end=bisect_right(
                        newline_positions,
                        max(original_start, original_end - 1),
                    )
                    + 1,
                    page_start=(
                        bisect_right(page_break_positions, original_start) + 1
                        if page_break_positions
                        else None
                    ),
                    page_end=(
                        bisect_right(
                            page_break_positions,
                            max(original_start, original_end - 1),
                        )
                        + 1
                        if page_break_positions
                        else None
                    ),
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
                text TEXT NOT NULL,
                char_start INTEGER NOT NULL DEFAULT 0,
                char_end INTEGER NOT NULL DEFAULT 0,
                line_start INTEGER NOT NULL DEFAULT 1,
                line_end INTEGER NOT NULL DEFAULT 1,
                page_start INTEGER,
                page_end INTEGER
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                chunk_id UNINDEXED,
                source_id UNINDEXED,
                text,
                tokenize = 'unicode61'
            );
            """
        )
        chunk_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(chunks)").fetchall()
        }
        for name, definition in (
            ("char_start", "INTEGER NOT NULL DEFAULT 0"),
            ("char_end", "INTEGER NOT NULL DEFAULT 0"),
            ("line_start", "INTEGER NOT NULL DEFAULT 1"),
            ("line_end", "INTEGER NOT NULL DEFAULT 1"),
            ("page_start", "INTEGER"),
            ("page_end", "INTEGER"),
        ):
            if name not in chunk_columns:
                self.connection.execute(f"ALTER TABLE chunks ADD COLUMN {name} {definition}")

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
                """
                INSERT INTO chunks(
                    chunk_id, source_id, ordinal, text,
                    char_start, char_end, line_start, line_end
                    , page_start, page_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        item.chunk_id,
                        item.source_id,
                        item.ordinal,
                        item.text,
                        item.char_start,
                        item.char_end,
                        item.line_start,
                        item.line_end,
                        item.page_start,
                        item.page_end,
                    )
                    for item in chunks
                ),
            )
            self.connection.executemany(
                "INSERT INTO chunks_fts(chunk_id, source_id, text) VALUES (?, ?, ?)",
                ((item.chunk_id, item.source_id, item.text) for item in chunks),
            )
        return result

    def prune_sources(self, active_source_ids: set[str] | frozenset[str]) -> tuple[str, ...]:
        if any(not isinstance(source_id, str) for source_id in active_source_ids):
            raise TypeError("active_source_ids must contain strings")
        indexed_source_ids = {
            row[0] for row in self.connection.execute("SELECT source_id FROM sources")
        }
        removed_source_ids = tuple(sorted(indexed_source_ids - active_source_ids))
        with self.connection:
            self.connection.executemany(
                "DELETE FROM chunks_fts WHERE source_id = ?",
                ((source_id,) for source_id in removed_source_ids),
            )
            self.connection.executemany(
                "DELETE FROM sources WHERE source_id = ?",
                ((source_id,) for source_id in removed_source_ids),
            )
        return removed_source_ids

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
            SELECT
                chunks_fts.chunk_id,
                chunks_fts.source_id,
                chunks_fts.text,
                bm25(chunks_fts) AS rank,
                chunks.char_start,
                chunks.char_end,
                chunks.line_start,
                chunks.line_end,
                chunks.page_start,
                chunks.page_end
            FROM chunks_fts
            JOIN chunks ON chunks.chunk_id = chunks_fts.chunk_id
            WHERE chunks_fts MATCH ?
            ORDER BY rank, chunks_fts.source_id, chunks_fts.chunk_id
            LIMIT ?
            """,
            (safe_query, limit),
        ).fetchall()
        return tuple(SearchHit(*row) for row in rows)
