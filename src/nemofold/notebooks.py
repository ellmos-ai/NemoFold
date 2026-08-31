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
from .report_verifier import verify_run_report

NOTEBOOK_SCHEMA = "nemofold.research-notebook.v1"
MAX_NOTEBOOKS = 100
MAX_NOTEBOOK_BYTES = 1024 * 1024
MAX_NOTEBOOK_QUESTIONS = 200
MAX_NOTEBOOK_RUNS = 200
_NOTEBOOK_ID = re.compile(r"notebook_[A-Za-z0-9_-]+")
_RUN_ID = re.compile(r"[A-Za-z0-9_-]+")


def _text(value: Any, field: str, *, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{field} must not be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return normalized


def _provider_snapshot(value: Any) -> dict[str, object] | None:
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
        raise ValueError("notebook provider_id is unsupported")
    descriptor = PROVIDER_DESCRIPTORS[provider_id]
    config = ProviderConfig(
        provider_id=provider_id,
        model=_text(model, "provider model", maximum=200),
        max_output_tokens=value.get("max_output_tokens", 32_768),
        timeout_seconds=value.get("timeout_seconds", 1_800),
        api_key="notebook-validation" if descriptor.api_key_env else None,
    )
    return {
        "provider_id": config.provider_id,
        "model": config.model,
        "max_output_tokens": config.max_output_tokens,
        "timeout_seconds": config.timeout_seconds,
    }


@dataclass(frozen=True, slots=True)
class ResearchNotebookStore:
    base_dir: Path
    allowed_roots: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_dir", Path(self.base_dir).resolve())
        if not self.allowed_roots:
            raise ValueError("research notebook store requires at least one allowed root")
        if not self.gate.path_allowed(str(self.root)):
            raise PermissionError("research notebook store is outside the configured allow roots")

    @property
    def root(self) -> Path:
        return self.base_dir / "run-reports" / "web-console" / "notebooks"

    @property
    def gate(self) -> PolicyGate:
        return PolicyGate(PolicyConfig(allowed_roots=self.allowed_roots))

    def save(self, value: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "notebook_id",
            "name",
            "goal",
            "job",
            "provider",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown notebook field: {unknown[0]}")
        notebook_id = value.get("notebook_id")
        previous: dict[str, Any] | None = None
        if notebook_id is not None:
            if not isinstance(notebook_id, str) or not _NOTEBOOK_ID.fullmatch(notebook_id):
                raise ValueError("notebook_id is invalid")
            previous = self.load(notebook_id)
        else:
            notebook_id = (
                f"notebook_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
            )
        raw_job = value.get("job")
        if not isinstance(raw_job, dict):
            raise ValueError("job must be an object")
        parsed = parse_job_payload(raw_job, base_dir=self.base_dir)
        if parsed.workflow != "evidence_analyst":
            raise ValueError("research notebooks require the evidence_analyst workflow")
        paths = (*parsed.input_roots, parsed.output_dir)
        if any(not self.gate.path_allowed(path) for path in paths):
            raise PermissionError("research notebook contains a path outside the allow roots")
        if not parsed.questions:
            raise ValueError("research notebook requires at least one question or prompt")
        if len(parsed.questions) > MAX_NOTEBOOK_QUESTIONS:
            raise ValueError("research notebook contains too many questions or prompts")
        question_values = [
            _text(item, "question", maximum=2000)
            for item in parsed.questions
        ]
        job_value: dict[str, object] = {
            "schema": "nemofold.job.v1",
            "workflow": parsed.workflow,
            "input_roots": list(parsed.input_roots),
            "target_roots": [],
            "output_dir": parsed.output_dir,
            "questions": question_values,
            "privacy_mode": parsed.privacy_mode.value,
            "action_mode": parsed.action_mode.value,
            "model_budget_usd": parsed.model_budget_usd,
            "parameters": to_primitive(parsed.parameters),
        }
        if parsed.model_id is not None:
            job_value["model_id"] = parsed.model_id
        now = datetime.now(UTC).isoformat()
        payload = {
            "schema": NOTEBOOK_SCHEMA,
            "notebook_id": notebook_id,
            "name": _text(value.get("name"), "name", maximum=120),
            "goal": _text(value.get("goal", ""), "goal", maximum=4000, required=False),
            "created_at": previous["created_at"] if previous else now,
            "updated_at": now,
            "job": job_value,
            "provider": _provider_snapshot(value.get("provider")),
            "approval_state": {
                "external_transfer": False,
                "file_actions": False,
                "note": "Approvals are never persisted in research notebooks.",
            },
            "runs": list(previous.get("runs", [])) if previous else [],
        }
        write_text_artifact(
            self.root / f"{notebook_id}.json",
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            "research-notebook",
        )
        return payload

    def load(self, notebook_id: str) -> dict[str, Any]:
        if not _NOTEBOOK_ID.fullmatch(notebook_id):
            raise ValueError("notebook_id is invalid")
        path = self.root / f"{notebook_id}.json"
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_NOTEBOOK_BYTES:
            raise ValueError("research notebook does not exist or exceeds the size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != NOTEBOOK_SCHEMA:
            raise ValueError("research notebook contract is invalid")
        return value

    def list(self) -> tuple[dict[str, Any], ...]:
        if not self.root.is_dir() or self.root.is_symlink():
            return ()
        entries: list[tuple[int, dict[str, Any]]] = []
        for path in self.root.glob("notebook_*.json"):
            try:
                value = self.load(path.stem)
                entries.append(
                    (
                        path.stat().st_mtime_ns,
                        {
                            "notebook_id": value["notebook_id"],
                            "name": value["name"],
                            "updated_at": value["updated_at"],
                            "question_count": len(value["job"]["questions"]),
                            "source_count": len(value["job"]["input_roots"]),
                            "run_count": len(value["runs"]),
                        },
                    )
                )
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                continue
        entries.sort(key=lambda item: item[0], reverse=True)
        return tuple(value for _, value in entries[:MAX_NOTEBOOKS])

    def link_run(self, notebook_id: str, run_id: str) -> dict[str, Any]:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id is invalid")
        notebook = self.load(notebook_id)
        ledger = Path(notebook["job"]["output_dir"]) / "ledger" / f"{run_id}.json"
        if not self.gate.path_allowed(str(ledger)) or not ledger.is_file() or ledger.is_symlink():
            raise ValueError("run ledger was not found in the notebook output scope")
        value = json.loads(ledger.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("run_id") != run_id:
            raise ValueError("run ledger does not match the requested run")
        verification = verify_run_report(ledger, allowed_roots=self.allowed_roots)
        run = {
            "run_id": run_id,
            "workflow": value.get("workflow"),
            "status": value.get("status"),
            "ledger_path": str(ledger),
            "verification": {
                "valid": verification.valid,
                "checked_artifacts": verification.checked_artifacts,
                "errors": list(verification.errors),
            },
            "linked_at": datetime.now(UTC).isoformat(),
        }
        runs = [item for item in notebook.get("runs", []) if item.get("run_id") != run_id]
        runs.insert(0, run)
        notebook["runs"] = runs[:MAX_NOTEBOOK_RUNS]
        notebook["updated_at"] = datetime.now(UTC).isoformat()
        write_text_artifact(
            self.root / f"{notebook_id}.json",
            json.dumps(notebook, indent=2, sort_keys=True) + "\n",
            "research-notebook",
        )
        return notebook
