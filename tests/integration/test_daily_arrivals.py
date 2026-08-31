from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.daily_arrivals import (
    OWNER_NOTES,
    OWNER_RESOLVED,
    OWNER_UNSUPPORTED,
    arrivals_markdown,
    build_arrivals,
    resolve_owner,
    windows_task_xml,
)
from nemofold.job_io import parse_job_payload

NOTE = """Rechnung 2026-04.
Der Betrag betraegt 148 Euro. Zahlbar bis 1. Mai 2026. Danke fuer Ihren Auftrag.
"""


def _job(tmp_path: Path, documents: Path, output: Path, **parameters):
    return parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "daily_arrivals",
            "input_roots": [str(documents)],
            "output_dir": str(output),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": parameters,
        },
        base_dir=tmp_path,
    )


def test_owner_is_named_or_the_reason_is(tmp_path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")

    owner, status = resolve_owner(target)

    # Both outcomes are correct; what must never happen is a blank field with no
    # reason. On Windows the standard library genuinely cannot answer.
    assert status in {OWNER_RESOLVED, OWNER_UNSUPPORTED}
    if status == OWNER_RESOLVED:
        assert owner
    else:
        assert owner is None
        assert "cannot name a file owner" in OWNER_NOTES[status]


def test_arrival_carries_name_size_time_and_short_content(tmp_path) -> None:
    target = tmp_path / "rechnung.txt"
    target.write_text(NOTE, encoding="utf-8")

    report = build_arrivals(
        ((("src_a"), "rechnung.txt", str(target)),),
        {"src_a": NOTE},
        ("src_a",),
        max_sentences=2,
    )

    assert report.count == 1
    arrival = report.arrivals[0]
    assert arrival.display_name == "rechnung.txt"
    assert arrival.size_bytes == target.stat().st_size
    assert arrival.modified.endswith("+00:00")
    # Two sentences, and the German ordinal did not cut one in half.
    assert arrival.summary == "Rechnung 2026-04. Der Betrag betraegt 148 Euro."
    assert arrival.owner_status in {OWNER_RESOLVED, OWNER_UNSUPPORTED}


def test_only_new_sources_are_reported(tmp_path) -> None:
    target = tmp_path / "a.txt"
    target.write_text(NOTE, encoding="utf-8")
    records = ((("src_a"), "a.txt", str(target)), (("src_b"), "b.txt", str(target)))

    report = build_arrivals(records, {"src_a": NOTE, "src_b": NOTE}, ("src_b",))

    assert [arrival.source_id for arrival in report.arrivals] == ["src_b"]
    assert report.total_sources == 2


def test_markdown_states_the_owner_limit_and_refuses_a_scheduler_claim(tmp_path) -> None:
    target = tmp_path / "a.txt"
    target.write_text(NOTE, encoding="utf-8")
    report = build_arrivals(((("src_a"), "a.txt", str(target)),), {"src_a": NOTE}, ("src_a",))

    markdown = arrivals_markdown(report, title="Tagesbericht", output_dir="out")

    assert "## Owner field" in markdown
    assert OWNER_NOTES[report.owner_status] in markdown
    assert "## Standing routine" in markdown
    assert "NemoFold has no scheduler and does not start itself" in markdown
    assert "installing, inspecting and removing it stays with you" in markdown


def test_empty_run_says_nothing_arrived_rather_than_printing_nothing() -> None:
    report = build_arrivals((), {}, ())
    markdown = arrivals_markdown(report, title="Tagesbericht", output_dir="out")
    assert "No new file arrived since the last snapshot" in markdown


def test_task_snippet_is_a_file_the_user_installs() -> None:
    xml = windows_task_xml(job_path="C:/out/job.json", run_at="06:30:00")

    assert xml.startswith('<?xml version="1.0" encoding="UTF-16"?>')
    assert "It is NOT installed" in xml
    assert "schtasks /Create" in xml
    assert "schtasks /Delete" in xml
    assert "2026-01-01T06:30:00" in xml
    assert "-m nemofold run --job" in xml


def test_daily_arrivals_runs_end_to_end_and_compares_against_the_snapshot(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "rechnung.txt").write_text(NOTE, encoding="utf-8")
    output = tmp_path / "out"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))

    first = run_job(_job(tmp_path, documents, output, title="Tagesbericht"),
                    config, run_id="arrivals_first").report
    assert first.status is RunStatus.EXECUTED
    assert first.metadata["arrivals"] == 1
    assert first.metadata["task_installed_by_nemofold"] is False
    assert first.metadata["task_snippet_exported"] is True

    formats = {artifact.format for artifact in first.artifacts}
    assert {"daily-arrivals", "scheduled-task-template"} <= formats
    for artifact in first.artifacts:
        written = Path(artifact.path)
        assert written.is_file()
        assert artifact.sha256 == hashlib.sha256(written.read_bytes()).hexdigest()

    # Comparing against the first run's snapshot: nothing new since then.
    second = run_job(
        _job(tmp_path, documents, output, title="Tagesbericht",
             since_run_id="arrivals_first"),
        config,
        run_id="arrivals_second",
    ).report
    assert second.metadata["arrivals"] == 0

    # A file added afterwards is the only arrival against that same baseline.
    (documents / "mahnung.txt").write_text("Zweite Mahnung. Bitte zahlen.", encoding="utf-8")
    third = run_job(
        _job(tmp_path, documents, output, title="Tagesbericht",
             since_run_id="arrivals_first"),
        config,
        run_id="arrivals_third",
    ).report
    assert third.metadata["arrivals"] == 1

    markdown = next(
        Path(artifact.path)
        for artifact in third.artifacts
        if artifact.format == "daily-arrivals"
    ).read_text(encoding="utf-8")
    assert "mahnung.txt" in markdown
    assert "Standing routine" in markdown

    ledger = json.loads(
        (output / "ledger" / "arrivals_third.json").read_text(encoding="utf-8")
    )
    assert ledger["metadata"]["owner_status"] in {"resolved", "unavailable_on_platform"}
