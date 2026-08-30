from __future__ import annotations

import pytest

import nemofold.inventory as inventory_module
from nemofold.inventory import scan_paths, scan_root


def test_scan_is_deterministic_and_detects_changes_without_changing_source_id(tmp_path) -> None:
    root = tmp_path / "documents"
    root.mkdir()
    first_file = root / "b.txt"
    second_file = root / "a.md"
    first_file.write_text("first version", encoding="utf-8")
    second_file.write_text("stable", encoding="utf-8")

    first = scan_root(root)
    previous = first.hashes_by_source_id()
    first_file.write_text("second version", encoding="utf-8")
    second = scan_root(root, previous_hashes=previous)

    assert [record.display_name for record in first.records] == ["a.md", "b.txt"]
    assert first.new_source_ids == tuple(record.source_id for record in first.records)
    assert second.changed_source_ids == (first.records[1].source_id,)
    assert second.unchanged_source_ids == (first.records[0].source_id,)
    assert second.records[1].source_id == first.records[1].source_id
    assert second.records[1].sha256 != first.records[1].sha256


def test_scan_reports_deleted_and_unreadable_entries(tmp_path, monkeypatch) -> None:
    root = tmp_path / "documents"
    root.mkdir()
    present = root / "present.txt"
    gone = root / "gone.txt"
    present.write_text("present", encoding="utf-8")
    gone.write_text("gone", encoding="utf-8")
    previous = scan_root(root)
    gone_id = next(
        record.source_id for record in previous.records if record.display_name == "gone.txt"
    )
    gone.unlink()

    original_sha256_file = inventory_module._sha256_file

    def fail_for_present(path):
        if path == present:
            raise PermissionError("synthetic lock")
        return original_sha256_file(path)

    monkeypatch.setattr(inventory_module, "_sha256_file", fail_for_present)
    current = scan_root(root, previous_hashes=previous.hashes_by_source_id())

    assert current.deleted_source_ids == (gone_id,)
    assert current.records[0].extraction_status == "unreadable"
    assert current.records[0].sha256 == ""


def test_scan_paths_accepts_files_and_keeps_same_relative_names_distinct(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "same.txt").write_text("first", encoding="utf-8")
    (second / "same.txt").write_text("second", encoding="utf-8")
    standalone = tmp_path / "standalone.md"
    standalone.write_text("third", encoding="utf-8")

    result = scan_paths((first, second, standalone))

    assert len(result.records) == 3
    assert len({record.source_id for record in result.records}) == 3
    assert {record.display_name for record in result.records} == {
        "first/same.txt",
        "second/same.txt",
        "standalone.md",
    }
    assert result.roots == tuple(str(path.resolve()) for path in (first, second, standalone))


def test_scan_paths_rejects_nested_or_duplicate_roots(tmp_path) -> None:
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)

    with pytest.raises(ValueError, match="overlap"):
        scan_paths((root, nested))
    with pytest.raises(ValueError, match="duplicate"):
        scan_paths((root, root))
