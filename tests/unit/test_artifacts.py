from __future__ import annotations

from nemofold.artifacts import render_markdown, render_text, write_text_artifact
from nemofold.contracts import Claim, Coverage, EvidenceLocator


def test_renderers_preserve_claim_and_source_identity(tmp_path) -> None:
    claims = (
        Claim(
            statement="The current version is valid until December.",
            evidence=(
                EvidenceLocator(
                    source_id="src_current",
                    quote="Valid until 31 December 2026",
                    page=2,
                ),
            ),
        ),
    )
    coverage = Coverage(
        total_sources=2,
        read_sources=2,
        cited_sources=1,
        unread_source_ids=(),
        uncited_read_source_ids=("src_old",),
    )

    markdown = render_markdown("Version report", claims, coverage)
    text = render_text("Version report", claims, coverage)
    record = write_text_artifact(tmp_path / "report.md", markdown, "markdown")

    assert "src_current" in markdown and "src_current" in text
    assert "src_old" in markdown and "src_old" in text
    assert record.path == str(tmp_path / "report.md")
    assert len(record.sha256) == 64
