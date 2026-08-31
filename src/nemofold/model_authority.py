"""Which model a step runs on, and which level decided it.

Three levels can carry a preference - link, chain and the local default - and the
resolution is deliberately explicit, because "which model saw my documents" is
the one question a user must always be able to answer.

Default precedence is links_win: the most specific setting wins. A chain may
instead declare chain_wins, which exists for the opposite need - a
privacy-critical voyage that must run locally whatever its links say. That mode
overrides settings a person made, so it is marked in the library and carries an
optional reason.

Above all of it sits one rule that no mode, override or configuration can lift:
a chain declared local-only is a cap. A more exposed setting underneath it does
not quietly win and does not quietly lose either - it becomes a visible conflict
that needs a person, because silently escalating exposure is the single failure
this product cannot afford.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .providers import PROVIDER_DESCRIPTORS

LOCAL_ONLY = "local-only"
LOCAL_CORE = "nemofold-local-core"

AUTHORITY_LINKS_WIN = "links_win"
AUTHORITY_CHAIN_WINS = "chain_wins"
MODEL_AUTHORITIES = frozenset({AUTHORITY_LINKS_WIN, AUTHORITY_CHAIN_WINS})

LEVEL_RUN_OVERRIDE = "run-override"
LEVEL_LINK = "link"
LEVEL_CHAIN = "chain"
LEVEL_DEFAULT = "default"

RIGHTS_DRAFT_ONLY = "draft_only"
RIGHTS_SEND_WITH_CONFIRMATION = "send_with_confirmation"
RIGHTS_SEND_WHEN_ORDERED = "send_when_ordered"
OUTBOUND_RIGHTS = (
    RIGHTS_DRAFT_ONLY,
    RIGHTS_SEND_WITH_CONFIRMATION,
    RIGHTS_SEND_WHEN_ORDERED,
)


@dataclass(frozen=True, slots=True)
class ModelResolution:
    model: str
    level: str
    note: str
    needs_user_input: bool = False
    conflict: str | None = None
    overridden: dict[str, Any] | None = None

    @property
    def runnable(self) -> bool:
        return not self.needs_user_input


def endpoint_label(endpoint: Any) -> str:
    if not isinstance(endpoint, dict):
        return LOCAL_CORE
    return f"{endpoint.get('provider')}:{endpoint.get('model')}"


def is_external(endpoint: Any) -> bool:
    """True when the endpoint sends content off this host."""
    if not isinstance(endpoint, dict):
        return False
    descriptor = PROVIDER_DESCRIPTORS.get(str(endpoint.get("provider")))
    return descriptor is not None and descriptor.api_key_env is not None


def _preferred(pref: Any) -> dict[str, Any] | None:
    if isinstance(pref, dict):
        candidate = pref.get("preferred")
        return candidate if isinstance(candidate, dict) else None
    return None


def resolve_authority(
    *,
    step_pref: Any = None,
    chain_pref: Any = None,
    authority: str = AUTHORITY_LINKS_WIN,
    run_override: Any = None,
) -> ModelResolution:
    """Decide the model for one step and name the level that decided it."""
    if authority not in MODEL_AUTHORITIES:
        raise ValueError("model_authority must be links_win or chain_wins")
    capped = chain_pref == LOCAL_ONLY
    chain_endpoint = _preferred(chain_pref)
    step_endpoint = _preferred(step_pref)
    override_endpoint = run_override if isinstance(run_override, dict) else None

    if override_endpoint is not None:
        candidate, level = override_endpoint, LEVEL_RUN_OVERRIDE
        overridden = step_pref if isinstance(step_pref, dict) else None
    elif authority == AUTHORITY_CHAIN_WINS and chain_endpoint is not None:
        candidate, level = chain_endpoint, LEVEL_CHAIN
        overridden = step_pref if isinstance(step_pref, dict) else None
    elif step_endpoint is not None:
        candidate, level, overridden = step_endpoint, LEVEL_LINK, None
    elif chain_endpoint is not None:
        candidate, level, overridden = chain_endpoint, LEVEL_CHAIN, None
    else:
        candidate, level, overridden = None, LEVEL_DEFAULT, None

    if candidate is not None and capped and is_external(candidate):
        # The cap never resolves itself in either direction: escalating would
        # break the promise, and silently downgrading would hide that the
        # stored plan and the run disagree.
        return ModelResolution(
            model=LOCAL_CORE,
            level=level,
            note=(
                f"{endpoint_label(candidate)} was set at the {level} level, but this chain "
                "is declared local-only. Exposure is never raised automatically, so this "
                "step needs a decision before it runs."
            ),
            needs_user_input=True,
            conflict="local_only_cap",
            overridden=overridden,
        )

    if candidate is None:
        return ModelResolution(
            model=LOCAL_CORE,
            level=LEVEL_DEFAULT,
            note="No preference was set at any level; the local engine is the default.",
        )

    label = endpoint_label(candidate)
    if level == LEVEL_RUN_OVERRIDE:
        note = (
            f"{label} was chosen for this run only. Stored link and chain settings are "
            "unchanged."
        )
    elif level == LEVEL_CHAIN and overridden is not None:
        note = (
            f"{label} was set by the chain, which overrides this step's own setting "
            f"({endpoint_label(_preferred(overridden))})."
        )
    else:
        note = f"{label} was determined by the {level} level."
    return ModelResolution(
        model=label, level=level, note=note, overridden=overridden
    )


def resolve_rights(step_rights: Any = None, chain_rights: Any = None) -> tuple[str, str]:
    """Resolve the outbound-action right. Rights inherit links_win only.

    There is deliberately no chain_wins analogue here: a chain may cap how far a
    model reaches, but it must never be able to widen what a step is allowed to
    send on the user's behalf.
    """
    for value, level in ((step_rights, LEVEL_LINK), (chain_rights, LEVEL_CHAIN)):
        if value is None:
            continue
        if value not in OUTBOUND_RIGHTS:
            raise ValueError(
                "rights must be draft_only, send_with_confirmation or send_when_ordered"
            )
        return value, level
    return RIGHTS_DRAFT_ONLY, LEVEL_DEFAULT
