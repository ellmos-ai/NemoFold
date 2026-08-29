from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PolicyRule:
    scope: Path
    naming_template: str = "{stem}{suffix}"
    allowed_extensions: tuple[str, ...] = ()
    retention_action: str = "keep"
    original_policy: str = "keep"

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", Path(self.scope).resolve())
        object.__setattr__(
            self,
            "allowed_extensions",
            tuple(_normalize_extension(item) for item in self.allowed_extensions),
        )

    def render_name(self, source: str | Path) -> str:
        path = Path(source)
        rendered = self.naming_template.format(
            stem=path.stem,
            suffix=path.suffix.lower(),
            name=path.name,
        )
        if not rendered or rendered in {".", ".."} or Path(rendered).name != rendered:
            raise ValueError("naming template must produce one safe filename")
        return rendered


@dataclass(frozen=True, slots=True)
class PolicySet:
    rules: tuple[PolicyRule, ...]

    def resolve(self, source: str | Path) -> PolicyRule:
        candidate = Path(source).resolve()
        matches = [
            rule
            for rule in self.rules
            if candidate == rule.scope or candidate.is_relative_to(rule.scope)
        ]
        if not matches:
            raise LookupError(f"no policy covers source: {candidate}")
        return max(matches, key=lambda rule: len(rule.scope.parts))


@dataclass(frozen=True, slots=True)
class StoragePlan:
    source: str
    target: str
    allowed: bool
    reasons: tuple[str, ...]
    retention_action: str
    original_policy: str


def _normalize_extension(extension: str) -> str:
    normalized = extension.casefold()
    return normalized if normalized.startswith(".") else f".{normalized}"


def preview_storage(
    source: str | Path,
    target_dir: str | Path,
    rule: PolicyRule,
) -> StoragePlan:
    source_path = Path(source).resolve()
    target_root = Path(target_dir).resolve()
    reasons: list[str] = []
    try:
        target = target_root / rule.render_name(source_path)
    except (KeyError, ValueError):
        target = target_root / source_path.name
        reasons.append("invalid_naming_template")

    if not (source_path == rule.scope or source_path.is_relative_to(rule.scope)):
        reasons.append("source_outside_policy")
    if rule.allowed_extensions and source_path.suffix.casefold() not in rule.allowed_extensions:
        reasons.append("extension_not_allowed")
    if rule.retention_action == "hard_delete":
        reasons.append("hard_delete_disabled")
    if target.exists() and target != source_path:
        reasons.append("target_collision")

    return StoragePlan(
        source=str(source_path),
        target=str(target),
        allowed=not reasons,
        reasons=tuple(reasons),
        retention_action=rule.retention_action,
        original_policy=rule.original_policy,
    )
