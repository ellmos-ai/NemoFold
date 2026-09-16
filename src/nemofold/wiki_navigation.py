"""Wissensnavigation und MetaWiki-Export (Ellmos UC 38, 49).

Stellt sicher, dass exportierte Wissensgraphen und MetaWikis vollstaendig
navigierbar sind:
- Alle internen Querverweise und Markdown-Links werden auf Zielseiten geprueft.
- Gebrochene Links und Zyklen in Navigationshierarchien blockieren fail-closed.
- Gleiche Quell- und Claim-IDs werden bis in das MetaWiki-Manifest erhalten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .compose import WikiPage, slugify

# Regex to match markdown links: [Link Text](target)
_MD_LINK_PATTERN = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<target>[^)]+)\)")
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "ftp://")


@dataclass(frozen=True, slots=True)
class WikiLink:
    source_slug: str
    target_slug: str
    raw_target: str
    text: str
    line: int


@dataclass(frozen=True, slots=True)
class LinkVerificationReport:
    total_links: int
    valid_links: int
    broken_links: tuple[dict[str, Any], ...]

    @property
    def is_valid(self) -> bool:
        return len(self.broken_links) == 0


@dataclass(frozen=True, slots=True)
class HierarchyReport:
    is_acyclic: bool
    cycles: tuple[tuple[str, ...], ...]
    root_nodes: tuple[str, ...]
    depth: int


def extract_wiki_markdown_links(text: str, source_slug: str) -> list[WikiLink]:
    """Extract internal relative markdown links from a text body."""
    links: list[WikiLink] = []
    for line_idx, line in enumerate(text.splitlines(), start=1):
        for match in _MD_LINK_PATTERN.finditer(line):
            target = match.group("target").strip()
            text_snippet = match.group("text").strip()
            if any(target.startswith(prefix) for prefix in _EXTERNAL_PREFIXES):
                continue
            if target.startswith("#"):
                continue

            target_base = target.split("#", 1)[0].split("?", 1)[0]
            target_slug = target_base
            if target_slug.lower().endswith(".md"):
                target_slug = target_slug[:-3]

            links.append(
                WikiLink(
                    source_slug=source_slug,
                    target_slug=target_slug,
                    raw_target=target,
                    text=text_snippet,
                    line=line_idx,
                )
            )
    return links


def verify_wiki_links(
    pages: tuple[WikiPage, ...],
    index_text: str,
) -> LinkVerificationReport:
    """Verify that all internal links in pages and index point to existing slugs."""
    valid_slugs: set[str] = {"index"}
    for page in pages:
        valid_slugs.add(page.slug)
        valid_slugs.add(slugify(page.title))
        valid_slugs.add(slugify(page.source_id))
        stem = page.source_id.rsplit(".", 1)[0]
        valid_slugs.add(slugify(stem))
        title_stem = page.title.rsplit(".", 1)[0]
        valid_slugs.add(slugify(title_stem))

    all_links: list[WikiLink] = []
    all_links.extend(extract_wiki_markdown_links(index_text, source_slug="index"))
    for page in pages:
        all_links.extend(extract_wiki_markdown_links(page.body, source_slug=page.slug))

    broken: list[dict[str, Any]] = []
    valid_count = 0

    for link in all_links:
        target_keys = {
            link.target_slug,
            slugify(link.target_slug),
            slugify(link.raw_target),
            slugify(link.raw_target.split("#", 1)[0]),
        }
        if target_keys & valid_slugs:
            valid_count += 1
        else:
            broken.append(
                {
                    "source_slug": link.source_slug,
                    "target_slug": link.target_slug,
                    "raw_target": link.raw_target,
                    "text": link.text,
                    "line": link.line,
                }
            )

    return LinkVerificationReport(
        total_links=len(all_links),
        valid_links=valid_count,
        broken_links=tuple(broken),
    )


def check_hierarchy_acyclic(hierarchy: dict[str, list[str]]) -> HierarchyReport:
    """Check that parent-to-children hierarchy mapping contains no cycles."""
    if not hierarchy:
        return HierarchyReport(
            is_acyclic=True,
            cycles=(),
            root_nodes=(),
            depth=0,
        )

    all_parents = set(hierarchy.keys())
    all_children = {child for children in hierarchy.values() for child in children}
    roots = tuple(sorted(all_parents - all_children))

    visited: set[str] = set()
    rec_stack: list[str] = []
    cycles: list[tuple[str, ...]] = []
    max_depth = 0

    def dfs(node: str, depth: int) -> None:
        nonlocal max_depth
        max_depth = max(max_depth, depth)
        visited.add(node)
        rec_stack.append(node)

        for child in hierarchy.get(node, []):
            if child in rec_stack:
                cycle_start = rec_stack.index(child)
                cycle = tuple(rec_stack[cycle_start:] + [child])
                cycles.append(cycle)
            elif child not in visited:
                dfs(child, depth + 1)

        rec_stack.pop()

    for node in sorted(all_parents | all_children):
        if node not in visited:
            dfs(node, 1)

    return HierarchyReport(
        is_acyclic=len(cycles) == 0,
        cycles=tuple(cycles),
        root_nodes=roots,
        depth=max_depth,
    )


def render_metawiki_overview(
    title: str,
    pages: tuple[WikiPage, ...],
    hierarchy: dict[str, list[str]] | None = None,
    link_report: LinkVerificationReport | None = None,
) -> str:
    """Render comprehensive Markdown overview for MetaWiki export."""
    lines = [
        f"# MetaWiki: {title}",
        "",
        "## 1. Uebersicht & Navigationsstruktur",
        "",
        f"- **Seitenanzahl**: {len(pages)}",
        f"- **Querverweise geprueft**: {link_report.total_links if link_report else 0}",
        f"- **Gueltige Links**: {link_report.valid_links if link_report else 0}",
        f"- **Gebrochene Links**: {len(link_report.broken_links) if link_report else 0}",
        "",
        "## 2. Inhaltsverzeichnis (Alphabetisch)",
        "",
    ]
    for page in sorted(pages, key=lambda p: p.title):
        lines.append(f"- [{page.title}]({page.slug}.md) <sub>(Quelle: {page.source_id})</sub>")

    if hierarchy:
        lines.extend(["", "## 3. Hierarchische Wissensgliederung", ""])
        for parent, children in sorted(hierarchy.items()):
            lines.append(f"### {parent}")
            for child in children:
                lines.append(f"  - [{child}]({child}.md)")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_metawiki_manifest(
    *,
    title: str,
    run_id: str,
    pages: tuple[WikiPage, ...],
    wiki_dir: str,
    link_report: LinkVerificationReport,
    hierarchy_report: HierarchyReport,
) -> dict[str, Any]:
    """Build canonical nemofold.metawiki-manifest.v1 artifact."""
    page_records = [
        {
            "slug": page.slug,
            "title": page.title,
            "source_id": page.source_id,
            "filename": f"{page.slug}.md",
            "body_length": len(page.body),
        }
        for page in pages
    ]
    return {
        "schema": "nemofold.metawiki-manifest.v1",
        "run_id": run_id,
        "title": title,
        "wiki_dir": wiki_dir,
        "page_count": len(pages),
        "pages": page_records,
        "link_verification": {
            "total_links": link_report.total_links,
            "valid_links": link_report.valid_links,
            "broken_links": list(link_report.broken_links),
            "is_valid": link_report.is_valid,
        },
        "hierarchy_verification": {
            "is_acyclic": hierarchy_report.is_acyclic,
            "depth": hierarchy_report.depth,
            "root_nodes": list(hierarchy_report.root_nodes),
            "cycles": [list(c) for c in hierarchy_report.cycles],
        },
        "integrity_status": (
            "verified"
            if link_report.is_valid and hierarchy_report.is_acyclic
            else "failed"
        ),
    }
