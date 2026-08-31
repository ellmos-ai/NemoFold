from __future__ import annotations

import pytest

from nemofold.model_authority import (
    AUTHORITY_CHAIN_WINS,
    LEVEL_CHAIN,
    LEVEL_DEFAULT,
    LEVEL_LINK,
    LEVEL_RUN_OVERRIDE,
    LOCAL_CORE,
    LOCAL_ONLY,
    RIGHTS_DRAFT_ONLY,
    RIGHTS_SEND_WHEN_ORDERED,
    RIGHTS_SEND_WITH_CONFIRMATION,
    is_external,
    resolve_authority,
    resolve_rights,
)

EXTERNAL = {"preferred": {"provider": "openai", "model": "gpt-4o-mini"}}
LOCAL = {"preferred": {"provider": "ollama", "model": "qwen3"}}


# --------------------------------------------------------------------------- #
# Precedence
# --------------------------------------------------------------------------- #


def test_links_win_is_the_default_precedence() -> None:
    resolved = resolve_authority(step_pref=LOCAL, chain_pref=EXTERNAL)

    assert resolved.model == "ollama:qwen3"
    assert resolved.level == LEVEL_LINK
    assert "link level" in resolved.note


def test_the_chain_answers_when_the_link_is_silent() -> None:
    resolved = resolve_authority(step_pref=None, chain_pref=LOCAL)

    assert resolved.model == "ollama:qwen3"
    assert resolved.level == LEVEL_CHAIN


def test_without_any_preference_the_local_default_answers() -> None:
    resolved = resolve_authority()

    assert resolved.model == LOCAL_CORE
    assert resolved.level == LEVEL_DEFAULT
    assert "No preference was set at any level" in resolved.note


def test_chain_wins_overrides_the_link_and_says_so() -> None:
    resolved = resolve_authority(
        step_pref=EXTERNAL, chain_pref=LOCAL, authority=AUTHORITY_CHAIN_WINS
    )

    assert resolved.model == "ollama:qwen3"
    assert resolved.level == LEVEL_CHAIN
    assert "overrides this step's own setting" in resolved.note
    # The overridden setting is kept, not discarded, so the panel can show it.
    assert resolved.overridden == EXTERNAL


def test_chain_wins_still_leaves_the_link_in_charge_when_the_chain_is_silent() -> None:
    resolved = resolve_authority(
        step_pref=LOCAL, chain_pref=None, authority=AUTHORITY_CHAIN_WINS
    )

    assert resolved.level == LEVEL_LINK


def test_an_unknown_authority_is_refused() -> None:
    with pytest.raises(ValueError, match="links_win or chain_wins"):
        resolve_authority(authority="whatever_wins")


# --------------------------------------------------------------------------- #
# Per-run override
# --------------------------------------------------------------------------- #


def test_a_run_override_beats_every_stored_level() -> None:
    resolved = resolve_authority(
        step_pref=LOCAL,
        chain_pref=LOCAL,
        authority=AUTHORITY_CHAIN_WINS,
        run_override={"provider": "lm-studio", "model": "mistral"},
    )

    assert resolved.model == "lm-studio:mistral"
    assert resolved.level == LEVEL_RUN_OVERRIDE
    assert "for this run only" in resolved.note
    assert "Stored link and chain settings are unchanged" in resolved.note


# --------------------------------------------------------------------------- #
# The cap
# --------------------------------------------------------------------------- #


def test_a_local_only_chain_caps_an_external_link() -> None:
    resolved = resolve_authority(step_pref=EXTERNAL, chain_pref=LOCAL_ONLY)

    # Neither escalated nor silently downgraded: it needs a person.
    assert resolved.needs_user_input is True
    assert resolved.runnable is False
    assert resolved.conflict == "local_only_cap"
    assert resolved.model == LOCAL_CORE
    assert "declared local-only" in resolved.note
    assert "never raised automatically" in resolved.note


def test_the_cap_also_holds_against_a_run_override() -> None:
    resolved = resolve_authority(
        chain_pref=LOCAL_ONLY,
        run_override={"provider": "anthropic", "model": "claude-sonnet-4-5"},
    )

    assert resolved.needs_user_input is True
    assert resolved.conflict == "local_only_cap"


def test_the_cap_lets_a_local_setting_through() -> None:
    resolved = resolve_authority(step_pref=LOCAL, chain_pref=LOCAL_ONLY)

    assert resolved.needs_user_input is False
    assert resolved.model == "ollama:qwen3"
    assert resolved.level == LEVEL_LINK


def test_external_endpoints_are_recognised_by_their_key_requirement() -> None:
    assert is_external({"provider": "openai", "model": "x"}) is True
    assert is_external({"provider": "ollama", "model": "x"}) is False
    assert is_external(None) is False


# --------------------------------------------------------------------------- #
# Rights inherit links_win only
# --------------------------------------------------------------------------- #


def test_rights_default_to_draft_only() -> None:
    assert resolve_rights() == (RIGHTS_DRAFT_ONLY, LEVEL_DEFAULT)


def test_a_step_right_wins_over_the_chain() -> None:
    value, level = resolve_rights(RIGHTS_DRAFT_ONLY, RIGHTS_SEND_WHEN_ORDERED)

    # Rights have no chain_wins analogue: a chain must never widen what a step
    # may send on the user's behalf.
    assert (value, level) == (RIGHTS_DRAFT_ONLY, LEVEL_LINK)


def test_the_chain_right_applies_when_the_step_is_silent() -> None:
    assert resolve_rights(None, RIGHTS_SEND_WITH_CONFIRMATION) == (
        RIGHTS_SEND_WITH_CONFIRMATION,
        LEVEL_CHAIN,
    )


def test_an_unknown_right_is_refused() -> None:
    with pytest.raises(ValueError, match="draft_only"):
        resolve_rights("send_anything")
