from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from .contracts import UndoReceipt
from .storage_policy import PolicySet, StoragePlan, preview_storage


@dataclass(frozen=True, slots=True)
class RoutingRule:
    suffixes: tuple[str, ...]
    target_dir: Path

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "suffixes",
            tuple(
                item.casefold() if item.startswith(".") else f".{item.casefold()}"
                for item in self.suffixes
            ),
        )
        object.__setattr__(self, "target_dir", Path(self.target_dir).resolve())


def plan_inbox(
    sources: Iterable[str | Path],
    *,
    rules: tuple[RoutingRule, ...],
    policies: PolicySet,
) -> tuple[StoragePlan, ...]:
    plans: list[StoragePlan] = []
    for source in sources:
        source_path = Path(source).resolve()
        route = next(
            (rule for rule in rules if source_path.suffix.casefold() in rule.suffixes),
            None,
        )
        if route is None:
            plans.append(
                StoragePlan(
                    source=str(source_path),
                    target=str(source_path),
                    allowed=False,
                    reasons=("no_matching_route",),
                    retention_action="keep",
                    original_policy="keep",
                )
            )
            continue
        try:
            policy = policies.resolve(source_path)
        except LookupError:
            plans.append(
                StoragePlan(
                    source=str(source_path),
                    target=str(route.target_dir / source_path.name),
                    allowed=False,
                    reasons=("no_matching_policy",),
                    retention_action="keep",
                    original_policy="keep",
                )
            )
            continue
        plans.append(preview_storage(source_path, route.target_dir, policy))
    return tuple(plans)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def apply_move(plan: StoragePlan, *, approved: bool) -> UndoReceipt:
    if not approved:
        raise PermissionError("move requires immediate human approval")
    if not plan.allowed:
        raise PermissionError(f"blocked storage plan: {', '.join(plan.reasons)}")
    source = Path(plan.source)
    target = Path(plan.target)
    if not source.is_file():
        raise FileNotFoundError(source)
    if not target.parent.is_dir():
        raise FileNotFoundError(target.parent)
    if target.exists():
        raise FileExistsError(target)

    digest = _sha256(source)
    action_id = "move_" + hashlib.sha256(
        f"{source}|{target}|{digest}".encode()
    ).hexdigest()[:20]
    source.replace(target)
    return UndoReceipt(
        action_id=action_id,
        before={"path": str(source), "sha256": digest},
        after={"path": str(target), "sha256": digest},
        undo_plan={"action": "move", "source": str(target), "target": str(source)},
    )


def undo_move(receipt: UndoReceipt, *, approved: bool) -> UndoReceipt:
    if not approved:
        raise PermissionError("undo requires immediate human approval")
    if receipt.undo_plan.get("action") != "move":
        raise ValueError("unsupported undo action")
    source = Path(str(receipt.undo_plan["source"]))
    target = Path(str(receipt.undo_plan["target"]))
    if target.exists():
        raise FileExistsError(target)
    if not source.is_file():
        raise FileNotFoundError(source)
    if _sha256(source) != receipt.after.get("sha256"):
        raise RuntimeError("undo source changed after the original action")
    source.replace(target)
    return replace(receipt, status="undone")
