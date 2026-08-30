from __future__ import annotations

import json

import pytest

from nemofold.action_journal import ActionJournal
from nemofold.storage_policy import PolicyRule, preview_storage


def plans(tmp_path):
    source_root = tmp_path / "inbox"
    target_root = tmp_path / "archive"
    source_root.mkdir()
    target_root.mkdir()
    first = source_root / "a.txt"
    second = source_root / "b.txt"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    rule = PolicyRule(
        scope=source_root,
        allowed_extensions=(".txt",),
        original_policy="move",
    )
    return (
        preview_storage(first, target_root, rule),
        preview_storage(second, target_root, rule),
    )


def test_action_journal_is_idempotent_and_every_move_has_an_undo_receipt(tmp_path) -> None:
    move_plans = plans(tmp_path)
    journal = ActionJournal(tmp_path / "output" / "actions" / "run_1.json", run_id="run_1")

    journal.plan(move_plans)
    first = journal.execute(move_plans)
    second = journal.execute(move_plans)

    assert first == second
    assert len(first) == 2
    assert all(receipt.status == "available" for receipt in first)
    assert all(not (tmp_path / "inbox" / name).exists() for name in ("a.txt", "b.txt"))
    assert all((tmp_path / "archive" / name).is_file() for name in ("a.txt", "b.txt"))
    payload = json.loads(journal.path.read_text(encoding="utf-8"))
    assert {entry["status"] for entry in payload["entries"]} == {"executed"}
    assert all(entry["undo_receipt"] for entry in payload["entries"])

    undone = journal.undo()
    repeated = journal.undo()
    assert undone == repeated
    assert all(receipt.status == "undone" for receipt in undone)
    assert all((tmp_path / "inbox" / name).is_file() for name in ("a.txt", "b.txt"))


def test_action_journal_reconciles_move_completed_before_checkpoint(tmp_path) -> None:
    move_plans = plans(tmp_path)
    journal = ActionJournal(tmp_path / "output" / "actions" / "run_2.json", run_id="run_2")
    journal.plan(move_plans)
    source = tmp_path / "inbox" / "a.txt"
    source.replace(tmp_path / "archive" / "a.txt")

    receipts = journal.execute(move_plans)

    assert len(receipts) == 2
    assert all(receipt.status == "available" for receipt in receipts)


def test_action_journal_fails_closed_when_executed_target_was_modified(tmp_path) -> None:
    move_plans = plans(tmp_path)
    journal = ActionJournal(tmp_path / "output" / "actions" / "run_3.json", run_id="run_3")
    journal.plan(move_plans)
    journal.execute(move_plans)
    (tmp_path / "archive" / "a.txt").write_text("tampered", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed after execution"):
        journal.execute(move_plans)


def test_conversion_copy_keeps_original_and_undo_removes_only_generated_file(tmp_path) -> None:
    source_root = tmp_path / "documents"
    target_root = tmp_path / "converted"
    source_root.mkdir()
    target_root.mkdir()
    source = source_root / "note.txt"
    source.write_bytes(b"\xef\xbb\xbfLocal text")
    rule = PolicyRule(
        scope=source_root,
        allowed_extensions=(".txt",),
        conversion_target=".md",
        original_policy="keep",
    )
    conversion_plan = preview_storage(source, target_root, rule)
    journal = ActionJournal(tmp_path / "output" / "actions" / "convert.json", run_id="convert")

    receipts = journal.execute((conversion_plan,))

    target = target_root / "note.md"
    assert conversion_plan.operation == "convert_copy"
    assert source.read_bytes().startswith(b"\xef\xbb\xbf")
    assert target.read_text(encoding="utf-8") == "Local text"
    assert receipts[0].undo_plan["action"] == "delete_generated_copy"

    undone = journal.undo()

    assert source.is_file()
    assert not target.exists()
    assert undone[0].status == "undone"
