from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.chunk_export import (
    ChunkLimitExceeded,
    _windows,
    chunk_texts,
    validate_chunk_settings,
)
from nemofold.contracts import RunStatus
from nemofold.job_io import JobFileError, parse_job_payload
from nemofold.wizard import plan_voyage


def _job(tmp_path: Path, documents: Path, **parameters):
    return parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "chunk_export",
            "input_roots": [str(documents)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": parameters,
        },
        base_dir=tmp_path,
    )


def _run(tmp_path: Path, documents: Path, run_id: str, **parameters):
    return run_job(
        _job(tmp_path, documents, **parameters),
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id=run_id,
    )


@pytest.mark.parametrize("seed", range(4))
def test_windows_cover_every_character_and_always_advance(seed) -> None:
    rng = random.Random(seed)
    for _ in range(400):
        text = "".join(rng.choice("ab \n") for _ in range(rng.randint(1, 3000)))
        size = rng.randint(200, 700)
        overlap = rng.randint(0, size // 2)

        windows = _windows(text, size, overlap)

        assert windows[0][0] == 0
        assert windows[-1][1] == len(text)
        for (start, end), (next_start, _) in zip(windows, windows[1:], strict=False):
            assert start < next_start <= end
        assert all(0 < end - start <= size for start, end in windows)


def test_a_window_prefers_to_end_at_a_line_break() -> None:
    text = "".join(f"Zeile {index:03d} mit etwas Text.\n" for index in range(60))

    report = chunk_texts(("s",), {"s": text}, chunk_chars=300, overlap_chars=60)

    assert all(chunk.text.endswith("\n") for chunk in report.chunks[:-1])
    assert all(chunk.text.startswith("Zeile") for chunk in report.chunks)
    for chunk in report.chunks:
        assert text[chunk.char_start:chunk.char_end] == chunk.text
        assert text.splitlines()[chunk.line_start - 1] in chunk.text


def test_chunks_are_deterministic_and_hash_their_exact_text() -> None:
    texts = {"a": "Erster Absatz.\n" * 200, "b": "Zweiter Text ohne Umbruch " * 80}

    first = chunk_texts(("a", "b"), texts, chunk_chars=400, overlap_chars=80)
    second = chunk_texts(("a", "b"), texts, chunk_chars=400, overlap_chars=80)

    assert first == second
    assert first.chunks[0].chunk_id == "a:00000"
    for chunk in first.chunks:
        assert chunk.sha256 == hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()


def test_unread_and_empty_sources_stay_visible() -> None:
    report = chunk_texts(("read", "blank", "missing"), {"read": "Text.\n", "blank": " \n "})

    statuses = {item.source_id: item.status for item in report.sources}
    assert statuses == {"read": "chunked", "blank": "empty", "missing": "not_read"}
    assert report.chunked_source_ids == frozenset({"read"})


def test_a_corpus_over_the_bound_is_refused_whole() -> None:
    with pytest.raises(ChunkLimitExceeded) as caught:
        chunk_texts(("a",), {"a": "x" * 5000}, chunk_chars=500, overlap_chars=0, max_chunks=3)

    assert caught.value.needed == 10
    assert caught.value.limit == 3


@pytest.mark.parametrize(
    ("size", "overlap", "bound"),
    [(100, 0, 10), (1000, 600, 10), (1000, -1, 10), (1000, 0, 0), ("1000", 0, 10), (True, 0, 1)],
)
def test_unusable_settings_are_named(size, overlap, bound) -> None:
    with pytest.raises(ValueError):
        validate_chunk_settings(size, overlap, bound)


def test_bad_settings_stop_the_job_before_any_document_is_read(tmp_path) -> None:
    documents = tmp_path / "docs"
    documents.mkdir()

    with pytest.raises(JobFileError, match="overlap_chars"):
        _job(tmp_path, documents, chunk_chars=400, overlap_chars=300)
    with pytest.raises(JobFileError, match="unknown chunk_export parameter"):
        _job(tmp_path, documents, chunk_size=400)


def test_the_run_writes_anchored_chunks_and_a_verifiable_manifest(tmp_path) -> None:
    documents = tmp_path / "docs"
    (documents / "akte").mkdir(parents=True)
    (documents / "akte" / "brief.txt").write_text(
        "".join(f"Absatz {index}: Die Frist endet am 30.04.2026.\n" for index in range(40)),
        encoding="utf-8",
    )
    (documents / "leer.txt").write_text("\n\n", encoding="utf-8")

    result = _run(tmp_path, documents, "chunks", chunk_chars=400, overlap_chars=100)

    assert result.report.status is RunStatus.EXECUTED
    out = tmp_path / "out"
    manifest = json.loads((out / "chunks.chunk-manifest.json").read_text(encoding="utf-8"))
    raw = (out / "chunks.chunks.jsonl").read_bytes()
    lines = [json.loads(line) for line in raw.decode("utf-8").splitlines()]

    assert manifest["chunks_sha256"] == hashlib.sha256(raw).hexdigest()
    assert manifest["chunk_count"] == len(lines) > 1
    statuses = {item["source_name"]: item["status"] for item in manifest["sources"]}
    assert statuses == {"akte/brief.txt": "chunked", "leer.txt": "empty"}
    source = (documents / "akte" / "brief.txt").read_text(encoding="utf-8")
    for line in lines:
        assert line["source_name"] == "akte/brief.txt"
        assert source[line["char_start"]:line["char_end"]] == line["text"]
        assert str(tmp_path) not in json.dumps(line)
    assert result.report.metadata["sources_empty"] == ["leer.txt"]
    assert result.report.coverage.cited_sources == 1


def test_the_run_blocks_instead_of_exporting_part_of_the_corpus(tmp_path) -> None:
    documents = tmp_path / "docs"
    documents.mkdir()
    (documents / "lang.txt").write_text("Satz.\n" * 2000, encoding="utf-8")

    result = _run(
        tmp_path, documents, "too_many", chunk_chars=200, overlap_chars=0, max_chunks=5
    )

    assert result.report.status is RunStatus.BLOCKED
    assert "chunk_limit_exceeded" in result.report.errors
    assert result.report.metadata["max_chunks"] == 5
    assert not (tmp_path / "out" / "too_many.chunks.jsonl").exists()


def test_the_captains_desk_reaches_chunk_export() -> None:
    plan = plan_voyage(
        "schneide die akten in chunks für unser rag-system",
        input_roots=("examples/synthetic-case",),
    )

    assert "chunk_export" in [step.workflow for step in plan.steps]
