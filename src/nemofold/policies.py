"""Named rules and policies, and where they are bound.

Governance answers two different questions with two different objects. A rule
is one sentence a person can hold in their head ("attachments are never sent
without a confirmation"). A policy is a rule set, closer to a small skill: it
carries several statements and, where a workflow can consume it, a machine body
as well.

Both are stored objects with a binding list, and that is the whole point: one
rule bound to six voyages stays ONE object. Editing it edits every place it
applies, and the object itself shows where those places are. The alternative -
copying the sentence into six voyages - is how a rule quietly stops being one
rule.

Nothing here grants anything. A policy is a written expectation; the gates that
actually decide are the allow roots, the privacy mode, the action mode and the
per-run approvals, and none of them read this file.
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
from .delivery import validate_delivery_body
from .model_authority import (
    AUTHORITY_CHAIN_WINS,
    OUTBOUND_RIGHTS,
    RIGHTS_DRAFT_ONLY,
)
from .policy import PolicyConfig, PolicyGate

POLICY_SCHEMA = "nemofold.policy.v1"
FORM_POLICY = "policy"
FORM_RULE = "rule"
POLICY_FORMS = (FORM_POLICY, FORM_RULE)
KIND_CLEANUP = "cleanup_rules"
KIND_DELIVERY = "delivery_rules"
KIND_RIGHTS = "rights_profile"
KIND_RECIPIENTS = "recipient_classes"
KIND_CUSTOM = "custom"
POLICY_KINDS = (
    KIND_CLEANUP,
    KIND_DELIVERY,
    KIND_RIGHTS,
    KIND_RECIPIENTS,
    KIND_CUSTOM,
)
TARGET_VOYAGE = "voyage"
TARGET_STEP = "step"
POLICY_TARGETS = (TARGET_VOYAGE, TARGET_STEP)

MAX_POLICIES = 200
MAX_POLICY_BYTES = 256 * 1024
MAX_STATEMENTS = 40
MAX_STATEMENT_CHARS = 500
MAX_BINDINGS = 200

_POLICY_ID = re.compile(r"policy_[A-Za-z0-9_-]+")
_VOYAGE_REF = re.compile(r"(voyage|preset)_[A-Za-z0-9_-]+")


def _text(value: Any, field: str, *, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{field} must not be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return normalized


def validate_statements(value: Any, *, form: str) -> list[str]:
    """Check the readable body: one sentence for a rule, a set for a policy."""
    if not isinstance(value, list) or not value:
        raise ValueError("statements must be a non-empty list")
    if len(value) > MAX_STATEMENTS:
        raise ValueError(f"a policy may not exceed {MAX_STATEMENTS} statements")
    statements = [
        _text(item, "statement", maximum=MAX_STATEMENT_CHARS) for item in value
    ]
    if form == FORM_RULE and len(statements) != 1:
        raise ValueError(
            "a rule is exactly one sentence; save several sentences as a policy instead"
        )
    return statements


def validate_binding(value: Any, index: int) -> dict[str, Any]:
    """Check one place a rule applies."""
    allowed = {"target", "voyage_id", "step_index", "note"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(
            f"binding {index} may only carry target, voyage_id, step_index and note"
        )
    target = value.get("target")
    if target not in POLICY_TARGETS:
        raise ValueError(f"binding {index} target must be voyage or step")
    voyage_id = _text(value.get("voyage_id"), f"binding {index} voyage_id", maximum=200)
    if not _VOYAGE_REF.fullmatch(voyage_id):
        raise ValueError(f"binding {index} voyage_id is invalid")
    step_index = value.get("step_index")
    if target == TARGET_STEP:
        if isinstance(step_index, bool) or not isinstance(step_index, int) or step_index < 1:
            raise ValueError(f"binding {index} to a step requires a 1-based step_index")
    elif step_index is not None:
        raise ValueError(f"binding {index} to a voyage must not carry a step_index")
    return {
        "target": target,
        "voyage_id": voyage_id,
        "step_index": step_index if target == TARGET_STEP else None,
        "note": _text(value.get("note", ""), f"binding {index} note", maximum=400,
                      required=False),
    }


def validate_bindings(value: Any) -> list[dict[str, Any]]:
    raw = [] if value is None else value
    if not isinstance(raw, list) or len(raw) > MAX_BINDINGS:
        raise ValueError(f"bindings must be a list of at most {MAX_BINDINGS} entries")
    bindings = [validate_binding(item, index) for index, item in enumerate(raw, start=1)]
    seen = {(item["target"], item["voyage_id"], item["step_index"]) for item in bindings}
    if len(seen) != len(bindings):
        raise ValueError("the same place must not be bound twice")
    return bindings


def validate_body(value: Any, *, kind: str) -> dict[str, Any]:
    """Check the machine-readable half, which only some kinds have.

    A body is what a workflow can actually consume. It is deliberately optional:
    a policy that only a person reads is still a policy, and pretending an empty
    body configures something would be the dishonest half of this feature.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("body must be an object")
    if kind == KIND_RIGHTS:
        if set(value) - {"rights"}:
            raise ValueError("a rights_profile body may only carry rights")
        rights = value.get("rights")
        if rights not in OUTBOUND_RIGHTS:
            raise ValueError(
                "rights must be draft_only, send_with_confirmation or send_when_ordered"
            )
        return {"rights": rights}
    if kind == KIND_DELIVERY:
        return validate_delivery_body(value)
    if kind == KIND_RECIPIENTS:
        # Who may be written to under which right belongs to the register,
        # not to each job that happens to send something. A job may still
        # narrow it, which is why the job parameter stays.
        if set(value) - {"contact_book", "class_rights"}:
            raise ValueError(
                "a recipient_classes body may only carry contact_book and class_rights"
            )
        classes = value.get("class_rights") or {}
        if not isinstance(classes, dict):
            raise ValueError("class_rights must be an object")
        for name, right in classes.items():
            if not isinstance(name, str) or right not in OUTBOUND_RIGHTS:
                raise ValueError(
                    "every recipient class must map to draft_only, "
                    "send_with_confirmation or send_when_ordered"
                )
        return {
            "contact_book": _text(
                value.get("contact_book", ""), "contact_book", maximum=400,
                required=False,
            ),
            "class_rights": {str(k): str(v) for k, v in sorted(classes.items())},
        }
    if kind == KIND_CLEANUP:
        if set(value) - {"rules"}:
            raise ValueError("a cleanup_rules body may only carry rules")
        rules = value.get("rules", [])
        if not isinstance(rules, list) or any(not isinstance(item, dict) for item in rules):
            raise ValueError("cleanup rules must be a list of objects")
        checked: list[dict[str, Any]] = []
        for rule in rules:
            if set(rule) != {"suffixes", "target_root"}:
                raise ValueError("a cleanup rule holds only suffixes and target_root")
            suffixes = rule["suffixes"]
            if not isinstance(suffixes, list) or not suffixes or any(
                not isinstance(item, str) or not item.strip() for item in suffixes
            ):
                raise ValueError("cleanup rule suffixes must be non-empty strings")
            target_root = rule["target_root"]
            if isinstance(target_root, bool) or not isinstance(target_root, int):
                raise ValueError("cleanup rule target_root must be an integer")
            checked.append({"suffixes": list(suffixes), "target_root": target_root})
        return {"rules": checked}
    if value:
        raise ValueError(f"a {kind} policy has no machine body yet; keep it in statements")
    return {}


@dataclass(frozen=True, slots=True)
class PolicyStore:
    base_dir: Path
    allowed_roots: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_dir", Path(self.base_dir).resolve())
        if not self.allowed_roots:
            raise ValueError("policy store requires at least one allowed root")
        if not self.gate.path_allowed(str(self.root)):
            raise PermissionError("policy register is outside the configured allow roots")

    @property
    def root(self) -> Path:
        return self.base_dir / "run-reports" / "web-console" / "policies"

    @property
    def gate(self) -> PolicyGate:
        return PolicyGate(PolicyConfig(allowed_roots=self.allowed_roots))

    def save(self, value: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "policy_id", "name", "form", "kind", "description", "statements",
            "body", "applies_by_default", "bindings",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown policy field: {unknown[0]}")
        policy_id = value.get("policy_id")
        previous: dict[str, Any] | None = None
        if policy_id is not None:
            if not isinstance(policy_id, str) or not _POLICY_ID.fullmatch(policy_id):
                raise ValueError("policy_id is invalid")
            previous = self.load(policy_id)
        else:
            policy_id = f"policy_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"

        def kept(field: str, default: Any) -> Any:
            if field in value:
                return value[field]
            if previous is not None and field in previous:
                return previous[field]
            return default

        form = kept("form", FORM_RULE)
        if form not in POLICY_FORMS:
            raise ValueError("form must be policy or rule")
        kind = kept("kind", KIND_CUSTOM)
        if kind not in POLICY_KINDS:
            raise ValueError(
                "kind must be cleanup_rules, delivery_rules, rights_profile or custom"
            )
        applies_by_default = kept("applies_by_default", False)
        if not isinstance(applies_by_default, bool):
            raise ValueError("applies_by_default must be a boolean")
        now = datetime.now(UTC).isoformat()
        payload = {
            "schema": POLICY_SCHEMA,
            "policy_id": policy_id,
            "name": _text(value.get("name"), "name", maximum=120),
            "form": form,
            "kind": kind,
            "description": _text(
                kept("description", "") or "", "description", maximum=2000, required=False
            ),
            "statements": validate_statements(kept("statements", None), form=form),
            "body": validate_body(kept("body", None), kind=kind),
            "applies_by_default": applies_by_default,
            "bindings": validate_bindings(kept("bindings", None)),
            "created_at": previous["created_at"] if previous else now,
            "updated_at": now,
        }
        write_text_artifact(
            self.root / f"{policy_id}.json",
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            "policy",
        )
        return payload

    def load(self, policy_id: str) -> dict[str, Any]:
        if not _POLICY_ID.fullmatch(policy_id):
            raise ValueError("policy_id is invalid")
        path = self.root / f"{policy_id}.json"
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_POLICY_BYTES:
            raise ValueError("policy does not exist or exceeds the size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != POLICY_SCHEMA:
            raise ValueError("policy contract is invalid")
        return value

    def delete(self, policy_id: str) -> None:
        self.load(policy_id)
        (self.root / f"{policy_id}.json").unlink()

    def list(self) -> tuple[dict[str, Any], ...]:
        entries: list[tuple[int, dict[str, Any]]] = []
        if self.root.is_dir() and not self.root.is_symlink():
            for path in self.root.glob("policy_*.json"):
                try:
                    value = self.load(path.stem)
                except (KeyError, OSError, ValueError, json.JSONDecodeError):
                    continue
                entries.append((path.stat().st_mtime_ns, value))
        entries.sort(key=lambda item: item[0], reverse=True)
        return tuple(value for _, value in entries[:MAX_POLICIES])

    def bind(
        self,
        policy_id: str,
        *,
        target: str,
        voyage_id: str,
        step_index: int | None = None,
        bound: bool = True,
    ) -> dict[str, Any]:
        """Add or remove one place this rule applies, keeping it one object."""
        policy = self.load(policy_id)
        candidate = validate_binding(
            {"target": target, "voyage_id": voyage_id, "step_index": step_index}, 1
        )
        key = (candidate["target"], candidate["voyage_id"], candidate["step_index"])
        remaining = [
            item
            for item in policy["bindings"]
            if (item["target"], item["voyage_id"], item["step_index"]) != key
        ]
        bindings = [*remaining, candidate] if bound else remaining
        return self.save({"policy_id": policy_id, "name": policy["name"],
                          "bindings": bindings})

    def for_target(
        self, voyage_id: str, *, step_index: int | None = None
    ) -> tuple[dict[str, Any], ...]:
        """Every policy bound to this voyage, or to this step of it."""
        found = []
        for policy in self.list():
            for binding in policy["bindings"]:
                if binding["voyage_id"] != voyage_id:
                    continue
                if binding["target"] == TARGET_VOYAGE and step_index is None:
                    found.append(policy)
                    break
                if binding["target"] == TARGET_STEP and binding["step_index"] == step_index:
                    found.append(policy)
                    break
        return tuple(found)


def default_rights(policies: tuple[dict[str, Any], ...]) -> str:
    """The outbound right that applies when nobody said otherwise."""
    for policy in policies:
        if policy["kind"] == KIND_RIGHTS and policy["applies_by_default"]:
            rights = policy["body"].get("rights")
            if rights in OUTBOUND_RIGHTS:
                return str(rights)
    return RIGHTS_DRAFT_ONLY


def policy_exceptions(
    voyages: tuple[dict[str, Any], ...], policies: tuple[dict[str, Any], ...]
) -> tuple[dict[str, Any], ...]:
    """List where a saved voyage departs from what applies in general.

    The governance area shows the defaults; the departures live at the voyage
    that made them, because that is where someone can change them. This is the
    reverse index of that: what deviates, where, and from what - so a rule set
    can be read as "here is what holds, and here are the five known exceptions"
    instead of "here is what holds, somewhere".
    """
    baseline = default_rights(policies)
    rows: list[dict[str, Any]] = []
    for voyage in voyages:
        voyage_id = str(voyage.get("voyage_id", ""))
        name = str(voyage.get("name", ""))
        if voyage.get("model_authority") == AUTHORITY_CHAIN_WINS:
            rows.append(
                {
                    "voyage_id": voyage_id,
                    "voyage_name": name,
                    "scope": TARGET_VOYAGE,
                    "step_index": None,
                    "subject": "model_authority",
                    "value": AUTHORITY_CHAIN_WINS,
                    "baseline": "links_win",
                    "note": voyage.get("authority_reason", "")
                    or "This voyage overrides its links.",
                }
            )
        chain_rights = voyage.get("rights")
        if chain_rights and chain_rights != baseline:
            rows.append(
                {
                    "voyage_id": voyage_id,
                    "voyage_name": name,
                    "scope": TARGET_VOYAGE,
                    "step_index": None,
                    "subject": "rights",
                    "value": chain_rights,
                    "baseline": baseline,
                    "note": f"Outbound rights {chain_rights} instead of {baseline}.",
                }
            )
        for index, step in enumerate(voyage.get("steps", []), start=1):
            step_rights = step.get("rights")
            inherited = chain_rights or baseline
            if step_rights and step_rights != inherited:
                rows.append(
                    {
                        "voyage_id": voyage_id,
                        "voyage_name": name,
                        "scope": TARGET_STEP,
                        "step_index": index,
                        "subject": "rights",
                        "value": step_rights,
                        "baseline": inherited,
                        "note": f"Step {index} ({step.get('workflow')}) sends under "
                        f"{step_rights} instead of {inherited}.",
                    }
                )
    return tuple(rows)


def cleanup_rules_for_step(
    policies: tuple[dict[str, Any], ...], parameters: dict[str, Any]
) -> tuple[list[dict[str, Any]], str]:
    """Resolve the cleanup rules a step runs with, and say where they came from.

    The existing parameters path stays valid and stays first: a job that already
    declares its rules keeps them, because a bound policy silently replacing what
    someone wrote into the contract would be the worst kind of helpful.
    """
    declared = parameters.get("rules") or []
    if declared:
        return list(declared), "the job contract"
    bound = [
        policy
        for policy in policies
        if policy["kind"] == KIND_CLEANUP and policy["body"].get("rules")
    ]
    if not bound:
        return [], "nothing"
    rules: list[dict[str, Any]] = []
    names: list[str] = []
    for policy in bound:
        rules.extend(policy["body"]["rules"])
        names.append(policy["name"])
    return rules, f"policy {', '.join(names)}"


def resolve_refs(
    policies: tuple[dict[str, Any], ...],
    *,
    voyage_id: str,
    policy_refs: tuple[str, ...] = (),
    step_index: int | None = None,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    """Every policy that governs this place, however it was attached.

    Two ways of saying the same thing grew side by side: a binding stored on the
    policy, and a name listed on the voyage. Both are read here and folded into
    one answer, so a person does not have to know which mechanism somebody used.
    A name that matches nothing is reported rather than dropped - a reference to
    a policy that was deleted is a finding, not a blank.
    """
    by_id = {item["policy_id"]: item for item in policies}
    by_name = {item["name"].casefold(): item for item in policies}
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for policy in policies:
        for binding in policy.get("bindings", []):
            if binding.get("voyage_id") != voyage_id:
                continue
            target = binding.get("target")
            if target == TARGET_VOYAGE and step_index is None:
                break
            if target == TARGET_STEP and binding.get("step_index") == step_index:
                break
        else:
            continue
        if policy["policy_id"] not in seen:
            seen.add(policy["policy_id"])
            found.append(policy)
    unresolved: list[str] = []
    for ref in policy_refs:
        named = by_id.get(ref) or by_name.get(ref.casefold())
        if named is None:
            unresolved.append(ref)
            continue
        if named["policy_id"] not in seen:
            seen.add(named["policy_id"])
            found.append(named)
    return tuple(found), tuple(unresolved)
