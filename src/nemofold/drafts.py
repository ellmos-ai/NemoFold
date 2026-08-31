from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .artifacts import write_text_artifact
from .contracts import to_primitive
from .job_io import parse_job_payload
from .policy import PolicyConfig, PolicyGate
from .providers import PROVIDER_DESCRIPTORS, ProviderConfig

DRAFT_SCHEMA = "nemofold.web-draft.v1"
MAX_DRAFTS = 100
MAX_DRAFT_BYTES = 512 * 1024


def _validate_provider(value: Any) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("provider must be an object or null")
    allowed = {"provider_id", "model", "max_output_tokens", "timeout_seconds"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown provider field: {unknown[0]}")
    provider_id = value.get("provider_id")
    model = value.get("model")
    if not isinstance(provider_id, str) or provider_id not in PROVIDER_DESCRIPTORS:
        raise ValueError("draft provider_id is unsupported")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("draft provider model must not be blank")
    descriptor = PROVIDER_DESCRIPTORS[provider_id]
    config = ProviderConfig(
        provider_id=provider_id,
        model=model,
        max_output_tokens=value.get("max_output_tokens", 32_768),
        timeout_seconds=value.get("timeout_seconds", 1_800),
        api_key="draft-validation" if descriptor.api_key_env else None,
    )
    return {
        "provider_id": config.provider_id,
        "model": config.model,
        "max_output_tokens": config.max_output_tokens,
        "timeout_seconds": config.timeout_seconds,
    }


@dataclass(frozen=True, slots=True)
class DraftStore:
    base_dir: Path
    allowed_roots: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_dir", Path(self.base_dir).resolve())
        if not self.allowed_roots:
            raise ValueError("draft store requires at least one allowed root")
        if not self.gate.path_allowed(str(self.root)):
            raise PermissionError("draft inbox is outside the configured allow roots")

    @property
    def root(self) -> Path:
        return self.base_dir / "run-reports" / "web-console" / "drafts"

    @property
    def gate(self) -> PolicyGate:
        return PolicyGate(PolicyConfig(allowed_roots=self.allowed_roots))

    def save(
        self,
        job: dict[str, Any],
        *,
        provider: dict[str, Any] | None = None,
        name: str | None = None,
        source: str,
    ) -> dict[str, Any]:
        if source not in {"api", "cli", "mcp", "wizard"}:
            raise ValueError("draft source is invalid")
        parsed = parse_job_payload(job, base_dir=self.base_dir)
        paths = (*parsed.input_roots, *parsed.target_roots, parsed.output_dir)
        if any(not self.gate.path_allowed(path) for path in paths):
            raise PermissionError("draft contains a path outside the configured allow roots")
        if name is not None and (not isinstance(name, str) or not name.strip() or len(name) > 120):
            raise ValueError("draft name must contain 1 to 120 characters")
        provider_value = _validate_provider(provider)
        if provider_value is not None and parsed.workflow != "evidence_analyst":
            raise ValueError("provider drafts require the evidence_analyst workflow")
        job_value = {
            "schema": "nemofold.job.v1",
            "workflow": parsed.workflow,
            "input_roots": list(parsed.input_roots),
            "target_roots": list(parsed.target_roots),
            "output_dir": parsed.output_dir,
            "questions": list(parsed.questions),
            "privacy_mode": parsed.privacy_mode.value,
            "action_mode": parsed.action_mode.value,
            "model_budget_usd": parsed.model_budget_usd,
            "parameters": to_primitive(parsed.parameters),
        }
        if parsed.model_id is not None:
            job_value["model_id"] = parsed.model_id
        if parsed.resume_run_id is not None:
            job_value["resume_run_id"] = parsed.resume_run_id
        draft_id = f"draft_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
        payload = {
            "schema": DRAFT_SCHEMA,
            "draft_id": draft_id,
            "name": name.strip() if isinstance(name, str) else f"{parsed.workflow} draft",
            "created_at": datetime.now(UTC).isoformat(),
            "source": source,
            "job": job_value,
            "execution_mode": "provider" if provider_value is not None else "local-core",
            "provider": provider_value,
            "approval_state": {
                "external_transfer": False,
                "file_actions": False,
                "note": "Approvals are never persisted in drafts.",
            },
        }
        write_text_artifact(
            self.root / f"{draft_id}.json",
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            "web-draft",
        )
        return payload

    def load(self, draft_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"draft_[A-Za-z0-9_-]+", draft_id):
            raise ValueError("draft_id is invalid")
        path = self.root / f"{draft_id}.json"
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_DRAFT_BYTES:
            raise ValueError("draft does not exist or exceeds the size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != DRAFT_SCHEMA:
            raise ValueError("draft contract is invalid")
        return value

    def list(self) -> tuple[dict[str, Any], ...]:
        if not self.root.is_dir() or self.root.is_symlink():
            return ()
        entries: list[tuple[int, dict[str, Any]]] = []
        for path in self.root.glob("draft_*.json"):
            try:
                value = self.load(path.stem)
                entries.append(
                    (
                        path.stat().st_mtime_ns,
                        {
                            "draft_id": value["draft_id"],
                            "name": value["name"],
                            "created_at": value["created_at"],
                            "source": value["source"],
                            "workflow": value["job"]["workflow"],
                            "execution_mode": value["execution_mode"],
                            "provider_id": (
                                value["provider"].get("provider_id")
                                if isinstance(value.get("provider"), dict)
                                else None
                            ),
                        },
                    )
                )
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                continue
        entries.sort(key=lambda item: item[0], reverse=True)
        return tuple(value for _, value in entries[:MAX_DRAFTS])
