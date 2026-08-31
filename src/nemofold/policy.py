from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from .contracts import ActionMode, GateDecision, JobEnvelope, PrivacyMode

EXTERNAL_ALLOWED_FIELDS = (
    "contract_version",
    "workflow",
    "questions",
    "sources",
    "response_schema",
    "model",
    "run_id",
    "validation_command",
)


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    allowed_roots: tuple[str, ...]
    external_models_allowed: bool = False
    max_external_cost_usd: float = 0.0
    apply_actions_allowed: bool = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_external_cost_usd, bool)
            or not isinstance(self.max_external_cost_usd, (int, float))
            or not math.isfinite(self.max_external_cost_usd)
            or self.max_external_cost_usd < 0
        ):
            raise ValueError("max_external_cost_usd must be a finite non-negative number")


class PolicyGate:
    def __init__(self, config: PolicyConfig) -> None:
        self.config = config
        self._allowed_roots = tuple(Path(root).resolve() for root in config.allowed_roots)

    def path_allowed(self, path: str) -> bool:
        candidate = Path(path).resolve()
        return any(
            candidate == root or candidate.is_relative_to(root) for root in self._allowed_roots
        )

    def evaluate(self, job: JobEnvelope) -> GateDecision:
        reasons: list[str] = []

        if not job.input_roots or any(not self.path_allowed(path) for path in job.input_roots):
            reasons.append("input_path_not_allowed")
        if not self.path_allowed(job.output_dir):
            reasons.append("output_path_not_allowed")
        if any(not self.path_allowed(path) for path in job.target_roots):
            reasons.append("target_path_not_allowed")
        if job.action_mode is ActionMode.APPLY and not self.config.apply_actions_allowed:
            reasons.append("action_apply_not_approved")

        recipient: str | None = None
        allowed_fields: tuple[str, ...] = ()
        if job.requires_external_model:
            recipient = "nebius"
            allowed_fields = EXTERNAL_ALLOWED_FIELDS
            if not self.config.external_models_allowed:
                reasons.append("external_models_disabled")
            if job.privacy_mode is not PrivacyMode.ALLOW_ONCE:
                reasons.append("external_privacy_not_approved")
            if job.model_budget_usd <= 0:
                reasons.append("external_budget_missing")
            elif job.model_budget_usd > self.config.max_external_cost_usd:
                reasons.append("external_budget_exceeds_limit")

        return GateDecision(
            allowed=not reasons,
            reasons=tuple(reasons),
            allowed_fields=allowed_fields,
            recipient=recipient,
            max_cost_usd=min(job.model_budget_usd, self.config.max_external_cost_usd),
        )
