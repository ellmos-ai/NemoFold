"""The use-case library: named voyages a person saved, plus shipped specialists.

This is what "NemoFold adapts to your use cases" actually means. A voyage is an
ordered list of job steps someone kept under a name, and the library grows as
people keep more of them. Nothing here trains on anything: adaptation is a
growing library of saved plans, not a changed model.

Presets are shipped read-only specialists. They are visible in the library from
the first listing and can be copied into it, and they are never executed on
their own - a shipped file that could run itself would be exactly the ambient
authority this product refuses.
"""

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
from .model_authority import (
    AUTHORITY_CHAIN_WINS,
    AUTHORITY_LINKS_WIN,
    MODEL_AUTHORITIES,
    OUTBOUND_RIGHTS,
    is_external,
)
from .policy import PolicyConfig, PolicyGate
from .providers import PROVIDER_DESCRIPTORS

VOYAGE_SCHEMA = "nemofold.voyage.v1"
PRESET_SCHEMA = "nemofold.voyage-preset.v1"
MAX_VOYAGES = 200
MAX_VOYAGE_BYTES = 1024 * 1024
MAX_STEPS = 24
LOCAL_ONLY = "local-only"
VOYAGE_SOURCES = frozenset({"wizard", "manual", "preset"})
STATUS_RUNNABLE = "runnable"
STATUS_PENDING = "pending_capability"
VOYAGE_STATUSES = frozenset({STATUS_RUNNABLE, STATUS_PENDING})
MAX_POLICY_REFS = 20
PRESET_ROOT = Path(__file__).with_name("presets")

_VOYAGE_ID = re.compile(r"voyage_[A-Za-z0-9_-]+")
_PRESET_ID = re.compile(r"preset_[a-z0-9_]+")


def _text(value: Any, field: str, *, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{field} must not be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return normalized


def _endpoint(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) - {"provider", "model"}:
        raise ValueError(f"{field} must name a provider and a model")
    provider = value.get("provider")
    if not isinstance(provider, str) or provider not in PROVIDER_DESCRIPTORS:
        raise ValueError(f"{field} provider is unsupported")
    return {"provider": provider, "model": _text(value.get("model"), f"{field} model", maximum=200)}


def validate_model_pref(value: Any) -> dict[str, Any] | None:
    """Check a model preference without granting anything.

    A preference is a wish, not an authorisation: the external-model gate, the
    per-run approval and the budget still decide. The one rule enforced here is
    directional - a fallback may only move work to a *less* exposed place.
    """
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"preferred", "fallback"}:
        raise ValueError("model_pref may only carry preferred and fallback")
    preferred = _endpoint(value.get("preferred"), "preferred")
    fallback = value.get("fallback", LOCAL_ONLY)
    if fallback == LOCAL_ONLY:
        return {"preferred": preferred, "fallback": LOCAL_ONLY}
    resolved = _endpoint(fallback, "fallback")
    preferred_local = PROVIDER_DESCRIPTORS[preferred["provider"]].api_key_env is None
    fallback_local = PROVIDER_DESCRIPTORS[resolved["provider"]].api_key_env is None
    if preferred_local and not fallback_local:
        raise ValueError(
            "a fallback may only lower exposure: falling back from a local model to an "
            "external one would silently widen the transfer surface"
        )
    return {"preferred": preferred, "fallback": resolved}



def validate_rights(value, field: str):
    """Check an outbound-action right without granting it."""
    if value is None:
        return None
    if value not in OUTBOUND_RIGHTS:
        raise ValueError(
            f"{field} must be draft_only, send_with_confirmation or send_when_ordered"
        )
    return str(value)


def validate_policy_refs(value, field: str) -> list[str]:
    """Carry named policy references through untouched.

    Policies become first-class objects in a later wave. The field exists now so
    a person can already reference one without the stored schema having to be
    migrated later.
    """
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_POLICY_REFS:
        raise ValueError(f"{field} must be a list of at most {MAX_POLICY_REFS} names")
    refs = [_text(item, f"{field} entry", maximum=120) for item in value]
    if len(set(refs)) != len(refs):
        raise ValueError(f"{field} must not repeat a policy name")
    return refs


def validate_chain_model_pref(value):
    """A chain may name a model, or declare itself local-only as a cap."""
    if value == LOCAL_ONLY:
        return LOCAL_ONLY
    return validate_model_pref(value)


def _step(value: Any, index: int, *, base_dir: Path, gate: PolicyGate) -> dict[str, Any]:
    allowed = {
        "workflow", "job", "model_pref", "note", "reads_previous_output",
        "rights", "policy_refs",
    }
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(
            f"step {index} may only carry workflow, job, model_pref, note, "
            "reads_previous_output, rights and policy_refs"
        )
    reads_previous = value.get("reads_previous_output", False)
    if not isinstance(reads_previous, bool):
        raise ValueError(f"step {index} reads_previous_output must be a boolean")
    if reads_previous and index == 1:
        raise ValueError("the first step has no previous output to read")
    raw_job = value.get("job")
    if not isinstance(raw_job, dict):
        raise ValueError(f"step {index} requires a job object")
    parsed = parse_job_payload(raw_job, base_dir=base_dir)
    for path in (*parsed.input_roots, *parsed.target_roots, parsed.output_dir):
        if not gate.path_allowed(path):
            raise PermissionError(f"step {index} points outside the configured allow roots")
    job_value: dict[str, object] = {
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
    return {
        "workflow": parsed.workflow,
        "job": job_value,
        "model_pref": validate_model_pref(value.get("model_pref")),
        "note": _text(value.get("note", ""), "note", maximum=400, required=False),
        "reads_previous_output": reads_previous,
        "rights": validate_rights(value.get("rights"), f"step {index} rights"),
        "policy_refs": validate_policy_refs(
            value.get("policy_refs"), f"step {index} policy_refs"
        ),
    }


def load_presets() -> tuple[dict[str, Any], ...]:
    """Read the shipped specialists. They are sources to copy, never to run."""
    if not PRESET_ROOT.is_dir():
        return ()
    presets: list[dict[str, Any]] = []
    for path in sorted(PRESET_ROOT.glob("preset_*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or value.get("schema") != PRESET_SCHEMA:
            continue
        if not _PRESET_ID.fullmatch(str(value.get("preset_id", ""))):
            continue
        presets.append(value)
    return tuple(presets)


@dataclass(frozen=True, slots=True)
class VoyageStore:
    base_dir: Path
    allowed_roots: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_dir", Path(self.base_dir).resolve())
        if not self.allowed_roots:
            raise ValueError("voyage store requires at least one allowed root")
        if not self.gate.path_allowed(str(self.root)):
            raise PermissionError("voyage library is outside the configured allow roots")

    @property
    def root(self) -> Path:
        return self.base_dir / "run-reports" / "web-console" / "voyages"

    @property
    def gate(self) -> PolicyGate:
        return PolicyGate(PolicyConfig(allowed_roots=self.allowed_roots))

    def save(self, value: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "voyage_id", "name", "description", "steps", "source", "status",
            "missing_capability", "model_pref", "model_authority", "authority_reason",
            "confirm_external_authority", "rights", "policy_refs",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown voyage field: {unknown[0]}")
        voyage_id = value.get("voyage_id")
        previous: dict[str, Any] | None = None
        if voyage_id is not None:
            if not isinstance(voyage_id, str) or not _VOYAGE_ID.fullmatch(voyage_id):
                raise ValueError("voyage_id is invalid")
            previous = self.load(voyage_id)
        else:
            voyage_id = f"voyage_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
        status = value.get("status", STATUS_RUNNABLE)
        if status not in VOYAGE_STATUSES:
            raise ValueError("status must be runnable or pending_capability")
        missing = _text(
            value.get("missing_capability", ""),
            "missing_capability",
            maximum=200,
            required=False,
        )
        if status == STATUS_PENDING and not missing:
            raise ValueError(
                "a reservation must name the missing capability it is waiting for"
            )
        if status == STATUS_RUNNABLE and missing:
            raise ValueError("a runnable voyage cannot wait for a missing capability")
        raw_steps = value.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            # A reservation is still a plan someone wants; it needs at least one
            # step so the library shows what it is waiting to do.
            raise ValueError("a voyage requires at least one step")
        if len(raw_steps) > MAX_STEPS:
            raise ValueError(f"a voyage may not exceed {MAX_STEPS} steps")
        steps = [
            _step(item, index, base_dir=self.base_dir, gate=self.gate)
            for index, item in enumerate(raw_steps, start=1)
        ]
        source = value.get("source", "manual")
        if source not in VOYAGE_SOURCES:
            raise ValueError("voyage source must be wizard, manual or preset")
        authority = value.get("model_authority", AUTHORITY_LINKS_WIN)
        if authority not in MODEL_AUTHORITIES:
            raise ValueError("model_authority must be links_win or chain_wins")
        chain_pref = validate_chain_model_pref(value.get("model_pref"))
        reason = _text(
            value.get("authority_reason", ""),
            "authority_reason",
            maximum=500,
            required=False,
        )
        # chain_wins overrides settings a person made on the links, so an external
        # chain model is confirmed when it is set, not only when it runs.
        if (
            authority == AUTHORITY_CHAIN_WINS
            and isinstance(chain_pref, dict)
            and is_external(chain_pref.get("preferred"))
            and value.get("confirm_external_authority") is not True
        ):
            raise ValueError(
                "a chain that overrides its links with an external model must be "
                "confirmed at set time: pass confirm_external_authority"
            )
        now = datetime.now(UTC).isoformat()
        payload = {
            "schema": VOYAGE_SCHEMA,
            "voyage_id": voyage_id,
            "name": _text(value.get("name"), "name", maximum=120),
            "description": _text(
                value.get("description", ""), "description", maximum=2000, required=False
            ),
            "created_at": previous["created_at"] if previous else now,
            "updated_at": now,
            "source": source,
            "status": status,
            "missing_capability": missing,
            "model_pref": chain_pref,
            "model_authority": authority,
            "authority_reason": reason,
            "rights": validate_rights(value.get("rights"), "rights"),
            "policy_refs": validate_policy_refs(value.get("policy_refs"), "policy_refs"),
            "steps": steps,
            "approval_state": {
                "external_transfer": False,
                "file_actions": False,
                "note": "Approvals are never stored in the use-case library.",
            },
        }
        write_text_artifact(
            self.root / f"{voyage_id}.json",
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            "voyage",
        )
        return payload

    def load(self, voyage_id: str) -> dict[str, Any]:
        if not _VOYAGE_ID.fullmatch(voyage_id):
            raise ValueError("voyage_id is invalid")
        path = self.root / f"{voyage_id}.json"
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_VOYAGE_BYTES:
            raise ValueError("voyage does not exist or exceeds the size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != VOYAGE_SCHEMA:
            raise ValueError("voyage contract is invalid")
        return value

    def delete(self, voyage_id: str) -> None:
        """Remove one saved voyage. Presets are shipped sources and never deleted."""
        if _PRESET_ID.fullmatch(voyage_id):
            raise PermissionError("presets are read-only sources and cannot be deleted")
        self.load(voyage_id)
        (self.root / f"{voyage_id}.json").unlink()

    def list(self) -> tuple[dict[str, Any], ...]:
        entries: list[tuple[int, dict[str, Any]]] = []
        if self.root.is_dir() and not self.root.is_symlink():
            for path in self.root.glob("voyage_*.json"):
                try:
                    value = self.load(path.stem)
                except (KeyError, OSError, ValueError, json.JSONDecodeError):
                    continue
                entries.append(
                    (
                        path.stat().st_mtime_ns,
                        {
                            "voyage_id": value["voyage_id"],
                            "name": value["name"],
                            "description": value["description"],
                            "updated_at": value["updated_at"],
                            "source": value["source"],
                            "status": value.get("status", STATUS_RUNNABLE),
                            "missing_capability": value.get("missing_capability", ""),
                            "model_authority": value.get(
                                "model_authority", AUTHORITY_LINKS_WIN
                            ),
                            "authority_reason": value.get("authority_reason", ""),
                            "overrides_links": value.get("model_authority")
                            == AUTHORITY_CHAIN_WINS,
                            "step_count": len(value["steps"]),
                            "workflows": [step["workflow"] for step in value["steps"]],
                            "editable": True,
                        },
                    )
                )
        entries.sort(key=lambda item: item[0], reverse=True)
        saved = tuple(value for _, value in entries[:MAX_VOYAGES])
        shipped = tuple(
            {
                "voyage_id": preset["preset_id"],
                "name": preset["name"],
                "description": preset["description"],
                "updated_at": None,
                "source": "preset",
                "status": STATUS_RUNNABLE,
                "missing_capability": "",
                "model_authority": AUTHORITY_LINKS_WIN,
                "authority_reason": "",
                "overrides_links": False,
                "step_count": len(preset["steps"]),
                "workflows": [step["workflow"] for step in preset["steps"]],
                "editable": False,
            }
            for preset in load_presets()
        )
        return saved + shipped

    def copy_preset(
        self,
        preset_id: str,
        *,
        input_roots: tuple[str, ...],
        output_dir: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Copy a shipped specialist into the library, bound to your own folders.

        The preset carries workflow and parameters only. Roots and the output
        location are supplied here, so a shipped file never names a path on
        somebody else's machine and never runs by itself.
        """
        if not _PRESET_ID.fullmatch(preset_id):
            raise ValueError("preset_id is invalid")
        preset = next(
            (item for item in load_presets() if item["preset_id"] == preset_id), None
        )
        if preset is None:
            raise ValueError("preset does not exist")
        if not input_roots:
            raise ValueError("copying a preset requires at least one approved input root")
        steps = []
        for index, template in enumerate(preset["steps"], start=1):
            steps.append(
                {
                    "workflow": template["workflow"],
                    "job": {
                        "schema": "nemofold.job.v1",
                        "workflow": template["workflow"],
                        "input_roots": list(input_roots),
                        "output_dir": f"{output_dir.rstrip('/')}/voyage/{index:02d}-"
                        f"{template['workflow']}",
                        "questions": list(template.get("questions", [])),
                        "privacy_mode": "local_only",
                        "action_mode": "dry_run",
                        "model_budget_usd": 0,
                        "parameters": dict(template.get("parameters", {})),
                    },
                    "note": template.get("note", ""),
                    "reads_previous_output": bool(template.get("reads_previous_output", False)),
                }
            )
        return self.save(
            {
                "name": name or preset["name"],
                "description": preset["description"],
                "steps": steps,
                "source": "preset",
            }
        )
