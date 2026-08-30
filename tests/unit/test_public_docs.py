from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_MARKERS = {
    "{LIVE_INPUT_TOKENS}",
    "{LIVE_LATENCY_MS}",
    "{LIVE_MODEL_ID}",
    "{LIVE_OUTPUT_TOKENS}",
    "{LIVE_RESULT_STATUS}",
}


def _relative_markdown_targets(document: Path) -> list[str]:
    text = document.read_text(encoding="utf-8")
    targets: list[str] = []
    for raw_target in re.findall(r"!?(?:\[[^]]*\])\(([^)]+)\)", text):
        target_with_optional_title = raw_target.strip()
        if target_with_optional_title.startswith("<"):
            target = target_with_optional_title.split(">", 1)[0].lstrip("<")
        else:
            target = target_with_optional_title.split(maxsplit=1)[0]
        target = unquote(target.split("#", 1)[0].strip())
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        targets.append(target)
    return targets


def _resolves_with_exact_case(document: Path, target: str) -> bool:
    relative = Path(target)
    root_relative = target.startswith("/")
    current = REPO_ROOT if root_relative else document.parent
    parts = relative.parts[1:] if root_relative else relative.parts
    for part in parts:
        if part in {"", "."}:
            continue
        if part == "..":
            current = current.parent
            continue
        if not current.is_dir():
            return False
        exact = next((child for child in current.iterdir() if child.name == part), None)
        if exact is None:
            return False
        current = exact
    return current.exists()


def test_public_readme_and_media_plan_links_resolve() -> None:
    documents = (REPO_ROOT / "README.md", REPO_ROOT / "docs" / "jury-demo.md")
    missing = [
        target
        for document in documents
        for target in _relative_markdown_targets(document)
        if not _resolves_with_exact_case(document, target)
    ]

    assert missing == []


def test_root_relative_links_keep_exact_repository_case() -> None:
    readme = REPO_ROOT / "README.md"

    assert _resolves_with_exact_case(readme, "/docs/jury-demo.md") is True
    assert _resolves_with_exact_case(readme, "/Docs/jury-demo.md") is False


def test_jury_narration_keeps_live_evidence_gate() -> None:
    text = (REPO_ROOT / "docs" / "jury-demo.md").read_text(encoding="utf-8")
    primary_cut = text.split("## Alternate opening:", 1)[0]
    live_section = primary_cut.split(
        "### 2:08-2:43 — Mandatory live platform proof", 1
    )[1].split("### 2:43-2:58 — Close", 1)[0]
    live_spoken = live_section.split(
        "**Say only after a real successful verified run:**", 1
    )[1].split("**Current state:**", 1)[0]
    spoken_lines: list[str] = []
    in_spoken_block = False
    for line in primary_cut.splitlines():
        if line.strip() in {
            "**Say:**",
            "**Say only after a real successful verified run:**",
        }:
            in_spoken_block = True
            continue
        if in_spoken_block and line.startswith(">"):
            spoken_lines.append(line.lstrip("> ").strip())
        elif in_spoken_block and line.strip():
            in_spoken_block = False

    word_count = len(re.findall(r"[A-Za-z0-9_*'-]+", " ".join(spoken_lines)))
    marker_pattern = r"\{LIVE_[A-Z0-9_]+\}"
    markers = set(re.findall(marker_pattern, text))
    spoken_markers = set(re.findall(marker_pattern, live_spoken))
    implied_words_per_minute = word_count / (178 / 60)
    segment_rates: list[float] = []
    segment_pattern = re.compile(
        r"^### (\d):(\d{2})-(\d):(\d{2}) — .+?\n(.*?)(?=^### |^## )",
        re.MULTILINE | re.DOTALL,
    )
    for match in segment_pattern.finditer(primary_cut + "\n## END"):
        start = int(match[1]) * 60 + int(match[2])
        end = int(match[3]) * 60 + int(match[4])
        quoted = " ".join(
            line.lstrip("> ").strip()
            for line in match[5].splitlines()
            if line.startswith(">")
        )
        segment_words = len(re.findall(r"[A-Za-z0-9_*'-]+", quoted))
        assert end > start
        assert segment_words > 0
        segment_rates.append(segment_words / ((end - start) / 60))

    assert word_count >= 300
    assert 105 <= implied_words_per_minute <= 125
    assert len(segment_rates) == 7
    assert max(segment_rates) <= 130
    assert markers == LIVE_MARKERS
    assert spoken_markers == LIVE_MARKERS
    assert "**Capture status:** **OPEN" in live_section
    assert "**Current state:** **OPEN.**" in text
    assert live_section.index("**Current state:** **OPEN.**") > live_section.index(
        "{LIVE_RESULT_STATUS}"
    )
    assert "The final render is blocked while any `{LIVE_*}` marker remains." in text
    assert "below 180 seconds" in text
