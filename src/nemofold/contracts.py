from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum, StrEnum
from typing import Any

CONTRACT_VERSION = "nemofold.contracts.v1"


class PrivacyMode(StrEnum):
    LOCAL_ONLY = "local_only"
    PREVIEW = "preview"
    ALLOW_ONCE = "allow_once"


class ActionMode(StrEnum):
    DRY_RUN = "dry_run"
    APPLY = "apply"


class RunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    EXECUTED = "executed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    path: str
    display_name: str
    sha256: str
    mime_type: str
    extraction_status: str = "indexed"

    def external_descriptor(self) -> dict[str, str]:
        """Return source metadata that cannot reveal its local absolute path."""
        return {
            "display_name": self.display_name,
            "mime_type": self.mime_type,
            "sha256": self.sha256,
            "source_id": self.source_id,
        }


@dataclass(frozen=True, slots=True)
class EvidenceLocator:
    source_id: str
    quote: str
    page: int | None = None
    section: str | None = None


@dataclass(frozen=True, slots=True)
class Claim:
    statement: str
    evidence: tuple[EvidenceLocator, ...] = ()
    uncertainty: float = 0.0
    conflict_status: str = "none"


@dataclass(frozen=True, slots=True)
class Coverage:
    total_sources: int
    read_sources: int
    cited_sources: int
    unread_source_ids: tuple[str, ...] = ()
    uncited_read_source_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GateDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()
    allowed_fields: tuple[str, ...] = ()
    recipient: str | None = None
    max_cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    format: str
    path: str
    sha256: str
    status: str = "written"


@dataclass(frozen=True, slots=True)
class UndoReceipt:
    action_id: str
    before: dict[str, Any]
    after: dict[str, Any]
    undo_plan: dict[str, Any]
    status: str = "available"


@dataclass(frozen=True, slots=True)
class JobEnvelope:
    workflow: str
    input_roots: tuple[str, ...]
    output_dir: str
    questions: tuple[str, ...] = ()
    privacy_mode: PrivacyMode = PrivacyMode.LOCAL_ONLY
    action_mode: ActionMode = ActionMode.DRY_RUN
    model_id: str | None = None
    model_budget_usd: float = 0.0
    sources: tuple[SourceRecord, ...] = ()
    response_schema: str = "nemofold.claims.v1"

    @property
    def requires_external_model(self) -> bool:
        return self.model_id is not None

    def to_external_payload(self) -> dict[str, Any]:
        """Build the only payload shape accepted by an external model adapter."""
        payload = {
            "contract_version": CONTRACT_VERSION,
            "workflow": self.workflow,
            "questions": list(self.questions),
            "sources": [source.external_descriptor() for source in self.sources],
            "response_schema": self.response_schema,
        }
        if self.model_id is not None:
            payload["model"] = {
                "id": self.model_id,
                "max_cost_usd": self.model_budget_usd,
            }
        return payload


@dataclass(frozen=True, slots=True)
class RunReport:
    run_id: str
    idempotency_key: str
    workflow: str
    status: RunStatus
    actions: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    gate_decision: GateDecision | None = None
    coverage: Coverage | None = None
    artifacts: tuple[ArtifactRecord, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClaimValidation:
    verified: bool
    valid_locator_count: int
    invalid_locators: tuple[str, ...] = ()


def to_primitive(value: Any) -> Any:
    """Convert nested contracts to JSON-safe builtins without losing enum values."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {key: to_primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_primitive(item) for item in value]
    return value
