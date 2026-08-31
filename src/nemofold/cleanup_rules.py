from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import SourceRecord


@dataclass(frozen=True, slots=True)
class CleanupRuleSuggestion:
    suffixes: tuple[str, ...]
    target_root: int
    support: int
    examples: tuple[str, ...]
    explanation: str

    def to_payload(self) -> dict[str, object]:
        return {
            "suffixes": list(self.suffixes),
            "target_root": self.target_root,
            "support": self.support,
            "examples": list(self.examples),
            "explanation": self.explanation,
        }


def suggest_cleanup_rules(
    records: tuple[SourceRecord, ...],
    corrections: list[dict[str, Any]],
    *,
    min_support: int,
    target_root_count: int,
) -> tuple[CleanupRuleSuggestion, ...]:
    """Derive readable suffix rules from explicit user corrections.

    Suggestions are evidence only. The caller must never silently activate them.
    """

    by_name = {record.display_name.casefold(): record for record in records}
    by_path = {str(Path(record.path).resolve()).casefold(): record for record in records}
    targets_by_suffix: dict[str, Counter[int]] = defaultdict(Counter)
    examples_by_pair: dict[tuple[str, int], list[str]] = defaultdict(list)

    for correction in corrections:
        source_value = correction.get("source")
        target_value = correction.get("target_root")
        if not isinstance(source_value, str) or not source_value.strip():
            raise ValueError("cleanup correction source must be a non-empty string")
        if (
            isinstance(target_value, bool)
            or not isinstance(target_value, int)
            or not 0 <= target_value < target_root_count
        ):
            raise ValueError("cleanup correction target_root is invalid")
        lookup = source_value.strip().casefold()
        record = by_name.get(lookup) or by_path.get(str(Path(source_value).resolve()).casefold())
        if record is None:
            raise ValueError(
                "cleanup correction source is not in the approved inventory: "
                f"{source_value}"
            )
        suffix = Path(record.display_name).suffix.casefold() or "<no-extension>"
        if suffix == "<no-extension>":
            continue
        targets_by_suffix[suffix][target_value] += 1
        pair = (suffix, target_value)
        if record.display_name not in examples_by_pair[pair]:
            examples_by_pair[pair].append(record.display_name)

    suggestions: list[CleanupRuleSuggestion] = []
    for suffix, counts in sorted(targets_by_suffix.items()):
        target_root, support = counts.most_common(1)[0]
        if support < min_support or len(counts) != 1:
            continue
        display_suffix = "files without an extension" if suffix == "<no-extension>" else suffix
        suggestions.append(
            CleanupRuleSuggestion(
                suffixes=("" if suffix == "<no-extension>" else suffix,),
                target_root=target_root,
                support=support,
                examples=tuple(examples_by_pair[(suffix, target_root)][:5]),
                explanation=(
                    f"All {support} explicit corrections for {display_suffix} selected "
                    f"approved target root {target_root}."
                ),
            )
        )
    return tuple(suggestions)
