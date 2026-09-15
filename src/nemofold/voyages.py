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
MAX_TAGS = 12
SCHEDULE_TAG = "scheduled"
SCHEDULE_CADENCES = ("daily", "weekly", "monthly")
PRESET_ROOT = Path(__file__).with_name("presets")

_VOYAGE_ID = re.compile(r"voyage_[A-Za-z0-9_-]+")
_PRESET_ID = re.compile(r"preset_[a-z0-9_]+")
_TAG = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
_CLOCK = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")


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
    # Exposure is "does the content leave this host", not "is a key needed":
    # the subscription bridges need no key and still send it away.
    preferred_local = not PROVIDER_DESCRIPTORS[preferred["provider"]].external_transfer
    fallback_local = not PROVIDER_DESCRIPTORS[resolved["provider"]].external_transfer
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


def validate_schedule(value: Any) -> dict[str, Any] | None:
    """Check a declared standing routine.

    A schedule is a stated intention, not a running timer. NemoFold registers
    nothing with the operating system and starts nothing on its own; the field
    records when a person means to run this voyage, so the library can show it
    as a routine and so an exported task file can carry the right time.
    """
    if value is None:
        return None
    # installed_by_nemofold is derived, never taken from the request; accepting
    # the key lets a stored schedule pass back through validation unchanged.
    if not isinstance(value, dict) or set(value) - {
        "cadence",
        "at",
        "note",
        "installed_by_nemofold",
    }:
        raise ValueError("schedule may only carry cadence, at and note")
    cadence = value.get("cadence")
    if cadence not in SCHEDULE_CADENCES:
        raise ValueError("schedule cadence must be daily, weekly or monthly")
    at = _text(value.get("at", "07:00"), "schedule at", maximum=5)
    if not _CLOCK.fullmatch(at):
        raise ValueError("schedule at must be a 24-hour HH:MM time")
    return {
        "cadence": cadence,
        "at": at,
        "note": _text(value.get("note", ""), "schedule note", maximum=400, required=False),
        # Said in the stored object itself, so no reader of the file can mistake
        # a saved schedule for something NemoFold installed or will fire.
        "installed_by_nemofold": False,
    }


def validate_tags(value: Any, *, scheduled: bool) -> list[str]:
    """Check the thematic tags and derive the reserved scheduled tag.

    Tags are how a use case finds its room, so they are free-form on purpose -
    except `scheduled`, which is derived from the schedule field. A tag that
    claims a property the object does not have would send a voyage to a room it
    does not belong in, so setting it by hand is refused.
    """
    raw = [] if value is None else value
    if not isinstance(raw, list) or len(raw) > MAX_TAGS:
        raise ValueError(f"tags must be a list of at most {MAX_TAGS} names")
    tags: list[str] = []
    for item in raw:
        tag = _text(item, "tag", maximum=40).lower()
        if not _TAG.fullmatch(tag):
            raise ValueError("a tag must be lowercase letters, digits or hyphens")
        if tag == SCHEDULE_TAG and not scheduled:
            raise ValueError(
                "the scheduled tag is derived from the schedule field and cannot be set "
                "by hand: give the voyage a schedule instead"
            )
        if tag not in tags:
            tags.append(tag)
    if scheduled and SCHEDULE_TAG not in tags:
        tags.append(SCHEDULE_TAG)
    return sorted(tags)


def validate_chain_model_pref(value):
    """A chain may name a model, or declare itself local-only as a cap."""
    if value == LOCAL_ONLY:
        return LOCAL_ONLY
    return validate_model_pref(value)


def _step(value: Any, index: int, *, base_dir: Path, gate: PolicyGate) -> dict[str, Any]:
    allowed = {
        "workflow", "job", "model_pref", "note", "reads_previous_output",
        "rights", "policy_refs", "handoff",
    }
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(
            f"step {index} may only carry workflow, job, model_pref, note, "
            "reads_previous_output, handoff, rights and policy_refs"
        )
    reads_previous = value.get("reads_previous_output", False)
    if not isinstance(reads_previous, bool):
        raise ValueError(f"step {index} reads_previous_output must be a boolean")
    if reads_previous and index == 1:
        raise ValueError("the first step has no previous output to read")
    handoff = value.get("handoff")
    if handoff is not None:
        if index == 1:
            raise ValueError("the first step has no previous artifact to receive")
        if reads_previous:
            raise ValueError("handoff and reads_previous_output are mutually exclusive")
        if not isinstance(handoff, dict) or set(handoff) not in (
            {"format"}, {"format", "mode"}
        ):
            raise ValueError("handoff must name exactly one artifact format")
        format_name = handoff["format"]
        if not isinstance(format_name, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{0,79}", format_name
        ):
            raise ValueError("handoff format must be a lowercase artifact label")
        handoff = {"format": format_name}
        if "mode" in value["handoff"]:
            if (
                value["handoff"]["mode"] != "selected_sources"
                or format_name != "document-registry"
            ):
                raise ValueError(
                    "selected_sources requires document-registry to synopsis_merge"
                )
            handoff["mode"] = "selected_sources"
    raw_job = value.get("job")
    if not isinstance(raw_job, dict):
        raise ValueError(f"step {index} requires a job object")
    parsed = parse_job_payload(raw_job, base_dir=base_dir)
    if (handoff or {}).get("mode") == "selected_sources" and (
        parsed.workflow != "synopsis_merge"
    ):
        raise ValueError("selected_sources requires document-registry to synopsis_merge")
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
        "handoff": handoff,
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
            "confirm_external_authority", "rights", "policy_refs", "tags", "schedule",
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

        def kept(field: str, default: Any) -> Any:
            """Return a field from the request, or from the stored voyage.

            A client that reorders two steps sends steps and a name. Falling back
            to the type default there would quietly strip the tags, the schedule,
            the reservation status and the outbound rights - silent erasure by
            omission. Clearing a field stays possible by sending it as null.
            """
            if field in value:
                return value[field]
            if previous is not None and field in previous:
                return previous[field]
            return default

        status = kept("status", STATUS_RUNNABLE)
        if status not in VOYAGE_STATUSES:
            raise ValueError("status must be runnable or pending_capability")
        # The reservation reason only exists while the reservation does, so it is
        # inherited only while the status stays pending. Freeing a voyage by
        # sending status=runnable must not drag the old reason along.
        missing = _text(
            (kept("missing_capability", "") if status == STATUS_PENDING
             else value.get("missing_capability", "")) or "",
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
        for previous_step, next_step in zip(steps, steps[1:], strict=False):
            if (next_step.get("handoff") or {}).get("mode") == "selected_sources" and (
                previous_step["workflow"] != "document_registry"
            ):
                raise ValueError(
                    "selected_sources requires the immediately preceding document_registry"
                )
        source = kept("source", "manual")
        if source not in VOYAGE_SOURCES:
            raise ValueError("voyage source must be wizard, manual or preset")
        authority = kept("model_authority", AUTHORITY_LINKS_WIN)
        if authority not in MODEL_AUTHORITIES:
            raise ValueError("model_authority must be links_win or chain_wins")
        chain_pref = validate_chain_model_pref(kept("model_pref", None))
        reason = _text(
            kept("authority_reason", "") or "",
            "authority_reason",
            maximum=500,
            required=False,
        )
        # chain_wins overrides settings a person made on the links, so an external
        # chain model is confirmed when it is set, not only when it runs. "At set
        # time" is meant literally: an unchanged setting was already confirmed, so
        # re-saving a step order must not demand a confirmation nobody is giving.
        newly_set = previous is None or (
            previous.get("model_authority"),
            previous.get("model_pref"),
        ) != (authority, chain_pref)
        if (
            authority == AUTHORITY_CHAIN_WINS
            and isinstance(chain_pref, dict)
            and is_external(chain_pref.get("preferred"))
            and newly_set
            and value.get("confirm_external_authority") is not True
        ):
            raise ValueError(
                "a chain that overrides its links with an external model must be "
                "confirmed at set time: pass confirm_external_authority"
            )
        schedule = validate_schedule(kept("schedule", None))
        raw_tags = kept("tags", None)
        if "tags" not in value and schedule is None and isinstance(raw_tags, list):
            # The derived tag is inherited with the rest, so dropping the schedule
            # has to drop it too. Sending it by hand is still refused.
            raw_tags = [tag for tag in raw_tags if tag != SCHEDULE_TAG]
        now = datetime.now(UTC).isoformat()
        payload = {
            "schema": VOYAGE_SCHEMA,
            "voyage_id": voyage_id,
            "name": _text(value.get("name"), "name", maximum=120),
            "description": _text(
                kept("description", "") or "", "description", maximum=2000, required=False
            ),
            "created_at": previous["created_at"] if previous else now,
            "updated_at": now,
            "source": source,
            "status": status,
            "missing_capability": missing,
            "model_pref": chain_pref,
            "model_authority": authority,
            "authority_reason": reason,
            "rights": validate_rights(kept("rights", None), "rights"),
            "policy_refs": validate_policy_refs(kept("policy_refs", None), "policy_refs"),
            "schedule": schedule,
            "tags": validate_tags(raw_tags, scheduled=schedule is not None),
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
                            "tags": list(value.get("tags") or []),
                            "schedule": value.get("schedule"),
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
                "tags": validate_tags(
                    preset.get("tags"), scheduled=preset.get("schedule") is not None
                ),
                "schedule": validate_schedule(preset.get("schedule")),
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
                # The room a specialist belongs in travels with the copy, so a
                # freshly copied use case is not homeless until someone tags it.
                "tags": [
                    tag for tag in preset.get("tags", []) if tag != SCHEDULE_TAG
                ],
                "schedule": preset.get("schedule"),
            }
        )
