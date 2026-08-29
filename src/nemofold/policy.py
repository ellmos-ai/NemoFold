from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .contracts import GateDecision, JobEnvelope, PrivacyMode

EXTERNAL_ALLOWED_FIELDS = (
    "contract_version",
    "workflow",
    "questions",
    "sources",
    "response_schema",
    "model",
)


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    allowed_roots: tuple[str, ...]
    external_models_allowed: bool = False
    max_external_cost_usd: float = 0.0


class PolicyGate:
    def __init__(self, config: PolicyConfig) -> None:
        self.config = config
        self._allowed_roots = tuple(Path(root).resolve() for root in config.allowed_roots)

    def _path_allowed(self, path: str) -> bool:
        candidate = Path(path).resolve()
        return any(
            candidate == root or candidate.is_relative_to(root) for root in self._allowed_roots
        )

    def evaluate(self, job: JobEnvelope) -> GateDecision:
        reasons: list[str] = []

        if not job.input_roots or any(not self._path_allowed(path) for path in job.input_roots):
            reasons.append("input_path_not_allowed")
        if not self._path_allowed(job.output_dir):
            reasons.append("output_path_not_allowed")

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
