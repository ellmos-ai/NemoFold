from __future__ import annotations

import json
import zipfile

from nemofold.bundle_export import create_text_bundle
from nemofold.contracts import SourceRecord


def source(source_id: str, name: str, status: str = "indexed") -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        path=f"C:/private/{name}",
        display_name=name,
        sha256=source_id.removeprefix("src_").ljust(64, "0")[:64],
        mime_type="text/plain",
        extraction_status=status,
    )


def test_bundle_contains_manifest_sources_and_explicit_gap(tmp_path) -> None:
    records = (
        source("src_a", "a.txt"),
        source("src_b", "b.txt"),
        source("src_locked", "locked.txt", "unreadable"),
    )

    result = create_text_bundle(
        records,
        {"src_a": "Alpha", "src_b": "Beta"},
        tmp_path,
        bundle_name="case_bundle",
    )

    bundle_text = result.bundle_path.read_text(encoding="utf-8")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    with zipfile.ZipFile(result.zip_path) as archive:
        names = sorted(archive.namelist())

    assert "[SOURCE src_a | a.txt]" in bundle_text
    assert "[SOURCE src_b | b.txt]" in bundle_text
    assert manifest["coverage"]["included"] == 2
    assert manifest["coverage"]["excluded"] == 1
    assert manifest["entries"][2]["reason"] == "unreadable"
    assert names == ["case_bundle.manifest.json", "case_bundle.txt"]


def test_bundle_is_byte_reproducible(tmp_path) -> None:
    records = (source("src_a", "a.txt"),)
    first = create_text_bundle(records, {"src_a": "Alpha"}, tmp_path / "one")
    second = create_text_bundle(records, {"src_a": "Alpha"}, tmp_path / "two")

    assert first.bundle_sha256 == second.bundle_sha256
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.zip_path.read_bytes() == second.zip_path.read_bytes()
