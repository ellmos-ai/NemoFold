from __future__ import annotations

import json
from pathlib import Path

from nemofold.cli import main


def make_fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "synthetic-home"
    fixture.mkdir()
    (fixture / "current_policy.txt").write_text(
        "Coverage begins on 1 April 2026.\nValid until 31 December 2026.",
        encoding="utf-8",
    )
    (fixture / "old_policy.txt").write_text(
        "Coverage began on 1 April 2025.\nExpired on 31 December 2025.",
        encoding="utf-8",
    )
    return fixture


def test_offline_demo_writes_verified_report_and_coverage_gap(tmp_path, capsys) -> None:
    fixture = make_fixture(tmp_path)
    output = tmp_path / "output"

    exit_code = main(
        [
            "demo",
            "--input",
            str(fixture),
            "--output",
            str(output),
            "--run-id",
            "demo_good",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    report = json.loads((output / "ledger" / "demo_good.json").read_text(encoding="utf-8"))
    artifact = (output / "demo_good.md").read_text(encoding="utf-8")
    assert exit_code == 0
    assert payload["status"] == "executed"
    assert payload["cloud_proof"] is False
    assert report["status"] == "executed"
    assert report["metadata"]["reasoning_adapter"] == "deterministic_demo"
    assert set(report["metadata"]["usecases"]) == {
        "UC01",
        "UC03",
        "UC04",
        "UC05",
        "UC06",
        "UC08",
        "UC09",
        "UC14",
    }
    assert (output / "bundles" / "demo_good.zip").is_file()
    assert (output / "demo_good.pdf").is_file()
    assert (output / "demo_good.docx").is_file()
    assert (output / "demo_good.odt").is_file()
    assert (output / "demo_good.digest.md").is_file()
    assert (output / "demo_good.context-receipts.json").is_file()
    assert "current_policy.txt" in artifact
    assert "old_policy.txt" in artifact
    assert (output / "workspaces" / "demo_good" / "inbox" / "incoming_note.txt").is_file()
    assert not (output / "workspaces" / "demo_good" / "documents" / "incoming_note.txt").exists()


def test_blocked_demo_never_claims_cloud_execution(tmp_path, capsys) -> None:
    fixture = make_fixture(tmp_path)
    output = tmp_path / "output"

    exit_code = main(
        [
            "demo",
            "--input",
            str(fixture),
            "--output",
            str(output),
            "--run-id",
            "demo_blocked",
            "--scenario",
            "blocked-external",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "blocked"
    assert payload["cloud_proof"] is False
    assert "external_privacy_not_approved" in payload["errors"]
