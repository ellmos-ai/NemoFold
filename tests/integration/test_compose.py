from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.compose import compose_guide, compose_wiki, guide_markdown, mine_patterns, slugify
from nemofold.contracts import RunStatus
from nemofold.job_io import parse_job_payload

LOGS = Path(__file__).resolve().parents[2] / "examples" / "synthetic-logs"
CASE = Path(__file__).resolve().parents[2] / "examples" / "synthetic-case"


def _run(tmp_path: Path, workflow: str, documents: Path, run_id: str, **parameters):
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": workflow,
            "input_roots": [str(documents)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": parameters,
        },
        base_dir=tmp_path,
    )
    return run_job(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path), str(documents))),
        run_id=run_id,
    )


# --------------------------------------------------------------------------- #
# The guide is a compilation, not a rewrite
# --------------------------------------------------------------------------- #


def test_a_repeated_paragraph_is_folded_once_and_counted() -> None:
    texts = {
        "a": "# Ablauf\n\nBitte immer zuerst den Beleg prüfen.\n",
        "b": "# Ablauf\n\nBitte immer zuerst den Beleg prüfen.\n",
        "c": "# Ablauf\n\nDanach den Vorgang abschließen.\n",
    }

    guide = compose_guide(("a", "b", "c"), texts, title="Leitfaden")

    section = next(item for item in guide.sections if item.title == "Ablauf")
    lines = [text for text, _, _ in section.paragraphs]
    assert lines.count("Bitte immer zuerst den Beleg prüfen.") == 1
    assert guide.struck == 1
    assert guide.replaces == ("a", "b", "c")


def test_every_guide_paragraph_keeps_the_line_it_came_from() -> None:
    texts = {"a": "# Ablauf\n\nBitte den Beleg prüfen.\n"}

    guide = compose_guide(("a",), texts)
    rendered = guide_markdown(guide, {"a": "handbuch.md"})

    # A guide that paraphrased its sources would be a new document nobody could
    # check against the old ones.
    assert "Bitte den Beleg prüfen." in rendered
    assert "handbuch.md, line 3" in rendered
    assert "Nothing here was rewritten" in rendered


def test_the_guide_says_which_documents_it_stands_in_for(tmp_path) -> None:
    result = _run(tmp_path, "guide_compose", CASE, "guide", formats=["md"])

    assert result.report.status is RunStatus.EXECUTED
    rendered = (tmp_path / "out" / "guide.guide.md").read_text(encoding="utf-8")
    assert "Was dieser Leitfaden zusammenfasst" in rendered
    assert "vernehmung-brandt.md" in rendered
    assert result.report.metadata["struck_repeats"] >= 0
    assert "checked against its original" in result.report.metadata["compilation_note"]


# --------------------------------------------------------------------------- #
# The wiki keeps its pages equal to their files
# --------------------------------------------------------------------------- #


def test_a_page_carries_its_document_unchanged(tmp_path) -> None:
    result = _run(tmp_path, "wiki_export", CASE, "wiki", wiki_dir="wiki")

    assert result.report.status is RunStatus.EXECUTED
    folder = tmp_path / "out" / "wiki"
    index = (folder / "index.md").read_text(encoding="utf-8")
    assert "[vernehmung-brandt.md](vernehmung-brandt-md.md)" in index
    page = (folder / "vernehmung-brandt-md.md").read_text(encoding="utf-8")
    original = (CASE / "vernehmung-brandt.md").read_text(encoding="utf-8")
    # Everything the source says is on the page, verbatim.
    for line in original.splitlines():
        if line.strip():
            assert line.strip() in page
    assert result.report.metadata["page_count"] == 12


def test_two_documents_with_the_same_name_get_two_pages() -> None:
    pages, _ = compose_wiki(
        ("a", "b"), {"a": "erste", "b": "zweite"}, labels={"a": "notiz.md", "b": "notiz.md"}
    )

    # A page silently overwriting another would lose a source without a word.
    assert [page.slug for page in pages] == ["notiz-md", "notiz-md-2"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Vernehmung Brandt.md", "vernehmung-brandt-md"), ("", "seite"), ("---", "seite")],
)
def test_a_page_name_is_stable_and_never_empty(value, expected) -> None:
    assert slugify(value) == expected


# --------------------------------------------------------------------------- #
# Pattern mining reports what recurs, not what is true
# --------------------------------------------------------------------------- #


def test_the_recurring_lines_are_found_with_their_sources(tmp_path) -> None:
    result = _run(tmp_path, "pattern_mining", LOGS, "mined", min_support=3, formats=["md"])

    assert result.report.status is RunStatus.EXECUTED
    payload = json.loads(
        (tmp_path / "out" / "mined.patterns.json").read_text(encoding="utf-8")
    )
    texts = {item["text"] for item in payload["patterns"]}
    assert "Der Vorgang wurde ohne Rückfrage geschlossen." in texts
    assert "Die Anfrage wurde an die Fachabteilung weitergeleitet." in texts
    top = payload["patterns"][0]
    assert top["support"] >= 3
    assert len(top["sources"]) >= 3
    assert all(name.endswith(".md") for name in top["sources"])


def test_a_line_that_occurs_once_is_not_a_pattern(tmp_path) -> None:
    _run(tmp_path, "pattern_mining", LOGS, "strict", min_support=3, formats=["md"])

    payload = json.loads(
        (tmp_path / "out" / "strict.patterns.json").read_text(encoding="utf-8")
    )
    texts = {item["text"] for item in payload["patterns"]}
    # A list where everything is a pattern is a list where nothing is.
    assert "Die Rechnung wurde storniert." not in texts
    assert all(item["support"] >= 3 for item in payload["patterns"])


def test_the_report_refuses_to_turn_frequency_into_a_rule(tmp_path) -> None:
    result = _run(tmp_path, "pattern_mining", LOGS, "note", min_support=2, formats=["md"])

    note = result.report.metadata["reading_note"]
    assert "not a rule about the world" in note
    assert "not that it is correct or that it should be" in note


def test_a_support_threshold_below_two_is_refused() -> None:
    with pytest.raises(ValueError, match="at least twice"):
        mine_patterns(("a",), {"a": "text"}, min_support=1)


def test_finding_nothing_still_produces_a_report(tmp_path) -> None:
    result = _run(tmp_path, "pattern_mining", LOGS, "none", min_support=99, formats=["md"])

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["pattern_count"] == 0
    findings = (tmp_path / "out" / "none_patterns.md").read_text(encoding="utf-8")
    assert "Das ist das Ergebnis, kein fehlender Bericht." in findings
