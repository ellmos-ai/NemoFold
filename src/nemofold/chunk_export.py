"""Chunk export: an approved corpus cut into retrieval units for a RAG index.

An external retrieval system wants pieces, not files. This module cuts every
readable source into overlapping chunks and gives each one the anchors the rest
of NemoFold keeps for a claim: the source it came from, the character offsets
and lines it spans, and a hash of its exact text. A chunk that cannot be traced
back to its place in the original is a quote without a citation.

Three rules hold the export honest:

* Deterministic. The same corpus and the same settings yield the same chunk ids,
  the same boundaries and the same hashes, so a re-export can be diffed against
  the index it is meant to replace.
* Complete. The chunk size describes a retrieval unit, never a reading budget.
  Every character of every read source lands in at least one chunk. A corpus
  that would need more chunks than the declared bound is refused as a whole
  rather than exported in part, because a silently truncated index answers
  questions as if the missing documents did not exist.
* Visible. A source that could not be read, or that holds no text, stays in the
  manifest with that status instead of vanishing from it.
"""

from __future__ import annotations

import bisect
import hashlib
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

CHUNK_SCHEMA = "nemofold.chunk-export.v1"
DEFAULT_CHUNK_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 200
DEFAULT_MAX_CHUNKS = 20000
MIN_CHUNK_CHARS = 200
MAX_CHUNK_CHARS = 20000
MAX_CHUNKS_LIMIT = 200000
# A rough, model-neutral estimate. Real tokenizers differ by language and
# vocabulary, so the number is labelled an estimate wherever it is shown.
CHARS_PER_TOKEN = 4


class ChunkLimitExceeded(ValueError):
    """The corpus needs more chunks than the declared bound allows."""

    def __init__(self, needed: int, limit: int) -> None:
        super().__init__(f"corpus needs {needed} chunks, the declared bound is {limit}")
        self.needed = needed
        self.limit = limit


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_id: str
    source_id: str
    index: int
    char_start: int
    char_end: int
    line_start: int
    line_end: int
    text: str
    sha256: str

    @property
    def token_estimate(self) -> int:
        return math.ceil(len(self.text) / CHARS_PER_TOKEN)


@dataclass(frozen=True, slots=True)
class SourceChunking:
    source_id: str
    status: str
    char_count: int
    chunk_count: int


@dataclass(frozen=True, slots=True)
class ChunkReport:
    chunks: tuple[Chunk, ...]
    sources: tuple[SourceChunking, ...]
    chunk_chars: int
    overlap_chars: int

    @property
    def chunked_source_ids(self) -> frozenset[str]:
        return frozenset(item.source_id for item in self.sources if item.chunk_count)


def validate_chunk_settings(
    chunk_chars: object, overlap_chars: object, max_chunks: object
) -> tuple[int, int, int]:
    """Return the three bounds as integers, or say which one is unusable."""
    values: dict[str, int] = {}
    for name, value in (
        ("chunk_chars", chunk_chars),
        ("overlap_chars", overlap_chars),
        ("max_chunks", max_chunks),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        values[name] = value
    size, overlap, bound = values["chunk_chars"], values["overlap_chars"], values["max_chunks"]
    if not MIN_CHUNK_CHARS <= size <= MAX_CHUNK_CHARS:
        raise ValueError(
            f"chunk_chars must be between {MIN_CHUNK_CHARS} and {MAX_CHUNK_CHARS}"
        )
    # Half the window is the most an overlap may take: beyond that, consecutive
    # chunks repeat more than they add and the index fills with near-duplicates.
    if not 0 <= overlap <= size // 2:
        raise ValueError("overlap_chars must be between 0 and half of chunk_chars")
    if not 1 <= bound <= MAX_CHUNKS_LIMIT:
        raise ValueError(f"max_chunks must be between 1 and {MAX_CHUNKS_LIMIT}")
    return size, overlap, bound


def _line_starts(text: str) -> list[int]:
    starts = [0]
    position = text.find("\n")
    while position != -1:
        starts.append(position + 1)
        position = text.find("\n", position + 1)
    return starts


def _windows(text: str, size: int, overlap: int) -> list[tuple[int, int]]:
    """Cut ``text`` into [start, end) windows that together cover all of it.

    A window ends at the last line break in its second half when there is one,
    so a chunk rarely splits a line; a single line longer than the window is cut
    hard. The next window starts ``overlap`` characters before the previous end,
    moved forward to a line start when one lies inside the overlap, and always
    strictly after the previous start, so the walk terminates.
    """
    windows: list[tuple[int, int]] = []
    length = len(text)
    start = 0
    while start < length:
        end = min(start + size, length)
        if end < length:
            cut = text.rfind("\n", start + size // 2, end)
            if cut != -1:
                end = cut + 1
        windows.append((start, end))
        if end >= length:
            break
        next_start = max(end - overlap, start + 1)
        if overlap:
            line_start = text.find("\n", next_start, end)
            if line_start != -1 and line_start + 1 < end:
                next_start = line_start + 1
        start = next_start
    return windows


def chunk_texts(
    source_ids: Iterable[str],
    texts: Mapping[str, str],
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
) -> ChunkReport:
    """Chunk every read source in inventory order.

    ``source_ids`` is the whole inventory; a source absent from ``texts`` was
    not readable and is reported as ``not_read``. Raises ``ChunkLimitExceeded``
    instead of returning a partial export.
    """
    size, overlap, bound = validate_chunk_settings(chunk_chars, overlap_chars, max_chunks)
    planned: list[tuple[str, str, list[tuple[int, int]]]] = []
    sources: list[SourceChunking] = []
    total = 0
    for source_id in source_ids:
        if source_id not in texts:
            sources.append(SourceChunking(source_id, "not_read", 0, 0))
            continue
        text = texts[source_id]
        windows = _windows(text, size, overlap) if text.strip() else []
        status = "chunked" if windows else "empty"
        sources.append(SourceChunking(source_id, status, len(text), len(windows)))
        planned.append((source_id, text, windows))
        total += len(windows)
    if total > bound:
        raise ChunkLimitExceeded(total, bound)

    chunks: list[Chunk] = []
    for source_id, text, windows in planned:
        starts = _line_starts(text)
        for index, (start, end) in enumerate(windows):
            piece = text[start:end]
            chunks.append(
                Chunk(
                    chunk_id=f"{source_id}:{index:05d}",
                    source_id=source_id,
                    index=index,
                    char_start=start,
                    char_end=end,
                    line_start=bisect.bisect_right(starts, start),
                    line_end=bisect.bisect_right(starts, max(start, end - 1)),
                    text=piece,
                    sha256=hashlib.sha256(piece.encode("utf-8")).hexdigest(),
                )
            )
    return ChunkReport(
        chunks=tuple(chunks),
        sources=tuple(sources),
        chunk_chars=size,
        overlap_chars=overlap,
    )


def chunk_record(chunk: Chunk, labels: Mapping[str, str] | None = None) -> dict[str, object]:
    """One JSONL line. The display name is relative; no absolute path leaves."""
    names = labels or {}
    return {
        "schema": CHUNK_SCHEMA,
        "chunk_id": chunk.chunk_id,
        "source_id": chunk.source_id,
        "source_name": names.get(chunk.source_id, chunk.source_id),
        "index": chunk.index,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "token_estimate": chunk.token_estimate,
        "sha256": chunk.sha256,
        "text": chunk.text,
    }


def chunk_manifest(
    report: ChunkReport,
    *,
    labels: Mapping[str, str] | None = None,
    source_hashes: Mapping[str, str] | None = None,
    chunks_file: str,
    chunks_sha256: str,
) -> dict[str, object]:
    names = labels or {}
    hashes = source_hashes or {}
    return {
        "schema": f"{CHUNK_SCHEMA}.manifest",
        "chunk_chars": report.chunk_chars,
        "overlap_chars": report.overlap_chars,
        "chunk_count": len(report.chunks),
        "token_estimate_total": sum(chunk.token_estimate for chunk in report.chunks),
        "token_estimate_note": (
            f"Estimated at {CHARS_PER_TOKEN} characters per token. Real tokenizers "
            "differ by model and language; treat it as an order of magnitude."
        ),
        "chunks_file": chunks_file,
        "chunks_sha256": chunks_sha256,
        "sources": [
            {
                "source_id": item.source_id,
                "source_name": names.get(item.source_id, item.source_id),
                "source_sha256": hashes.get(item.source_id, ""),
                "status": item.status,
                "char_count": item.char_count,
                "chunk_count": item.chunk_count,
            }
            for item in report.sources
        ],
        "completeness_note": (
            "Every character of every read source is inside at least one chunk. "
            "A source marked not_read or empty contributes nothing to the index and "
            "is listed so that its absence is visible, not silent."
        ),
    }


def chunk_summary_markdown(
    report: ChunkReport, *, title: str, labels: Mapping[str, str] | None = None
) -> str:
    names = labels or {}
    lines = [
        f"# {title}",
        "",
        f"- Chunks: {len(report.chunks)}",
        f"- Chunk size: {report.chunk_chars} characters, overlap {report.overlap_chars}",
        "- Estimated tokens: "
        f"{sum(chunk.token_estimate for chunk in report.chunks)} "
        f"(about {CHARS_PER_TOKEN} characters per token)",
        "",
        "| Source | Status | Characters | Chunks |",
        "|---|---|---:|---:|",
    ]
    for item in report.sources:
        name = names.get(item.source_id, item.source_id).replace("|", "\\|")
        lines.append(f"| {name} | {item.status} | {item.char_count} | {item.chunk_count} |")
    lines.extend(
        [
            "",
            "Every chunk carries its source id, character offsets, lines and a SHA-256 of "
            "its exact text, so any retrieved passage can be checked against the file "
            "it came from.",
            "",
        ]
    )
    return "\n".join(lines)
