from __future__ import annotations

import hashlib
from pathlib import Path

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.job_io import parse_job_payload
from nemofold.synopsis_merge import merge_synopsis, synopsis_markdown

OFFER_A = """# Leistung
Die Deckung gilt weltweit.
Beitrag: 148 Euro pro Jahr

# Kontakt
Berater: Frau Meier
"""

OFFER_B = """# Leistung
Die Deckung gilt weltweit ausser USA.
Beitrag: 160 Euro pro Jahr

# Kuendigung
Frist: drei Monate zum Jahresende
"""

PLAIN_NOTE = """Kurze Notiz ohne Ueberschrift.
Zweite Zeile der Notiz.
"""


def test_merge_keeps_the_anchor_of_every_paragraph() -> None:
    synopsis = merge_synopsis(("src_a", "src_b"), {"src_a": OFFER_A, "src_b": OFFER_B})

    titles = [section.title for section in synopsis.sections]
    assert titles == ["Leistung", "Kontakt", "Kuendigung"]

    leistung = synopsis.sections[0]
    # Both offers contribute to the same section, each paragraph keeping its source.
    assert {
        paragraph.anchor.source_id for paragraph in leistung.paragraphs
    } == {"src_a", "src_b"}
    first = leistung.paragraphs[0]
    assert first.text == "Die Deckung gilt weltweit."
    assert (first.anchor.source_id, first.anchor.line) == ("src_a", 2)


def test_disagreeing_labels_become_a_visible_conflict() -> None:
    synopsis = merge_synopsis(("src_a", "src_b"), {"src_a": OFFER_A, "src_b": OFFER_B})

    assert len(synopsis.conflicts) == 1
    conflict = synopsis.conflicts[0]
    assert conflict.label == "beitrag"
    assert conflict.section == "Leistung"
    assert {value for value, _ in conflict.values} == {
        "148 Euro pro Jahr",
        "160 Euro pro Jahr",
    }
    assert {anchor.source_id for _, anchor in conflict.values} == {"src_a", "src_b"}


def test_agreeing_labels_do_not_raise_a_conflict() -> None:
    synopsis = merge_synopsis(
        ("src_a", "src_b"), {"src_a": OFFER_A, "src_b": OFFER_A.replace("weltweit", "global")}
    )
    assert synopsis.conflicts == ()


def test_documents_without_headings_merge_into_one_body() -> None:
    synopsis = merge_synopsis(
        ("src_a", "src_b"), {"src_a": PLAIN_NOTE, "src_b": PLAIN_NOTE}
    )

    assert [section.title for section in synopsis.sections] == ["Document body"]
    # Merged, but every line still says where it came from.
    assert len(synopsis.sections[0].paragraphs) == 4
    assert {
        paragraph.anchor.source_id for paragraph in synopsis.sections[0].paragraphs
    } == {"src_a", "src_b"}


def test_markdown_shows_conflicts_before_the_merged_sections() -> None:
    synopsis = merge_synopsis(("src_a", "src_b"), {"src_a": OFFER_A, "src_b": OFFER_B})
    markdown = synopsis_markdown(synopsis, title="Angebotsvergleich")

    assert markdown.index("## Conflicts (1)") < markdown.index("## Leistung")
    assert "nothing was preferred automatically" in markdown
    assert "148 Euro pro Jahr — src_a, line 3" in markdown
    assert "Die Deckung gilt weltweit. [src_a:2]" in markdown


def test_synopsis_merge_runs_end_to_end_with_conflict_claims(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "angebot-a.txt").write_text(OFFER_A, encoding="utf-8")
    (documents / "angebot-b.txt").write_text(OFFER_B, encoding="utf-8")

    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "synopsis_merge",
            "input_roots": [str(documents)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {"formats": ["md", "pdf"], "title": "Angebotsvergleich"},
        },
        base_dir=tmp_path,
    )

    report = run_job(
        job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="synopsis_e2e"
    ).report

    assert report.status is RunStatus.EXECUTED
    assert report.metadata["conflicts"] == 1
    assert report.metadata["conflict_labels"] == ["beitrag"]
    assert "Leistung" in report.metadata["sections"]
    assert report.metadata["paragraphs"] >= 6

    formats = {artifact.format for artifact in report.artifacts}
    assert {"synopsis", "pdf", "markdown"} <= formats
    for artifact in report.artifacts:
        written = Path(artifact.path)
        assert written.is_file()
        assert artifact.sha256 == hashlib.sha256(written.read_bytes()).hexdigest()

    markdown = next(
        Path(artifact.path)
        for artifact in report.artifacts
        if artifact.format == "synopsis"
    ).read_text(encoding="utf-8")
    assert "## Conflicts (1)" in markdown
