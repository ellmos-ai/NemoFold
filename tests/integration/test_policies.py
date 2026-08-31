from __future__ import annotations

from pathlib import Path

import pytest

from nemofold.policies import (
    POLICY_SCHEMA,
    PolicyStore,
    cleanup_rules_for_step,
    default_rights,
    policy_exceptions,
)


def _store(tmp_path: Path) -> PolicyStore:
    return PolicyStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))


def _rule(**overrides) -> dict:
    payload = {
        "name": "Anhänge nie ohne Bestätigung",
        "form": "rule",
        "statements": ["Ein Anhang verlässt das Haus nur mit ausdrücklicher Bestätigung."],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Rules and policies are two shapes of one object
# --------------------------------------------------------------------------- #


def test_a_rule_is_saved_loaded_and_listed(tmp_path) -> None:
    store = _store(tmp_path)

    saved = store.save(_rule())
    loaded = store.load(saved["policy_id"])

    assert saved["schema"] == POLICY_SCHEMA
    assert saved["policy_id"].startswith("policy_")
    assert saved["form"] == "rule"
    assert saved["kind"] == "custom"
    assert saved["bindings"] == []
    assert loaded == saved
    assert [item["policy_id"] for item in store.list()] == [saved["policy_id"]]


def test_a_rule_is_exactly_one_sentence(tmp_path) -> None:
    with pytest.raises(ValueError, match="exactly one sentence"):
        _store(tmp_path).save(_rule(statements=["Erstens.", "Zweitens."]))


def test_a_policy_may_hold_several_statements(tmp_path) -> None:
    saved = _store(tmp_path).save(
        {
            "name": "Versand-Regelwerk",
            "form": "policy",
            "kind": "delivery_rules",
            "statements": ["Entwürfe zuerst.", "Empfänger werden benannt."],
        }
    )

    assert saved["form"] == "policy"
    assert len(saved["statements"]) == 2


def test_a_kind_without_a_machine_body_says_so(tmp_path) -> None:
    with pytest.raises(ValueError, match="no machine body yet"):
        _store(tmp_path).save(
            {
                "name": "Versand",
                "form": "policy",
                "kind": "delivery_rules",
                "statements": ["Entwürfe zuerst."],
                "body": {"channel": "email"},
            }
        )


# --------------------------------------------------------------------------- #
# One rule with many bindings stays one object
# --------------------------------------------------------------------------- #


def test_binding_the_same_rule_twice_keeps_one_object(tmp_path) -> None:
    store = _store(tmp_path)
    saved = store.save(_rule())

    store.bind(saved["policy_id"], target="voyage", voyage_id="voyage_a")
    bound = store.bind(
        saved["policy_id"], target="step", voyage_id="voyage_b", step_index=2
    )

    assert len(store.list()) == 1
    assert len(bound["bindings"]) == 2
    assert {item["voyage_id"] for item in bound["bindings"]} == {"voyage_a", "voyage_b"}


def test_binding_the_same_place_again_does_not_duplicate_it(tmp_path) -> None:
    store = _store(tmp_path)
    saved = store.save(_rule())

    store.bind(saved["policy_id"], target="voyage", voyage_id="voyage_a")
    bound = store.bind(saved["policy_id"], target="voyage", voyage_id="voyage_a")

    assert len(bound["bindings"]) == 1


def test_a_binding_can_be_taken_back(tmp_path) -> None:
    store = _store(tmp_path)
    saved = store.save(_rule())
    store.bind(saved["policy_id"], target="voyage", voyage_id="voyage_a")

    released = store.bind(
        saved["policy_id"], target="voyage", voyage_id="voyage_a", bound=False
    )

    assert released["bindings"] == []


def test_a_step_binding_needs_a_step_number(tmp_path) -> None:
    store = _store(tmp_path)
    saved = store.save(_rule())

    with pytest.raises(ValueError, match="1-based step_index"):
        store.bind(saved["policy_id"], target="step", voyage_id="voyage_a")


def test_for_target_separates_the_chain_from_its_steps(tmp_path) -> None:
    store = _store(tmp_path)
    chain_rule = store.save(_rule(name="Für die ganze Kette"))
    step_rule = store.save(_rule(name="Nur für Schritt 2"))
    store.bind(chain_rule["policy_id"], target="voyage", voyage_id="voyage_a")
    store.bind(step_rule["policy_id"], target="step", voyage_id="voyage_a", step_index=2)

    on_chain = store.for_target("voyage_a")
    on_step = store.for_target("voyage_a", step_index=2)
    on_other_step = store.for_target("voyage_a", step_index=1)

    assert [item["name"] for item in on_chain] == ["Für die ganze Kette"]
    assert [item["name"] for item in on_step] == ["Nur für Schritt 2"]
    assert on_other_step == ()


# --------------------------------------------------------------------------- #
# Defaults and their exceptions
# --------------------------------------------------------------------------- #


def test_the_default_right_is_draft_only_until_a_policy_says_otherwise(tmp_path) -> None:
    store = _store(tmp_path)

    assert default_rights(store.list()) == "draft_only"

    store.save(
        {
            "name": "Standardrechte",
            "form": "policy",
            "kind": "rights_profile",
            "statements": ["Versand nur nach Bestätigung."],
            "body": {"rights": "send_with_confirmation"},
            "applies_by_default": True,
        }
    )

    assert default_rights(store.list()) == "send_with_confirmation"


def test_exceptions_name_the_voyage_the_subject_and_the_baseline(tmp_path) -> None:
    policies = _store(tmp_path).list()
    voyages = (
        {
            "voyage_id": "voyage_a",
            "name": "Unfallakte",
            "model_authority": "chain_wins",
            "authority_reason": "Nur lokal, der Fall ist sensibel.",
            "rights": "send_with_confirmation",
            "steps": [
                {"workflow": "fact_distill", "rights": None},
                {"workflow": "controlled_email", "rights": "send_when_ordered"},
            ],
        },
    )

    rows = policy_exceptions(voyages, policies)

    subjects = [(row["subject"], row["scope"], row["value"]) for row in rows]
    assert ("model_authority", "voyage", "chain_wins") in subjects
    assert ("rights", "voyage", "send_with_confirmation") in subjects
    assert ("rights", "step", "send_when_ordered") in subjects
    step_row = next(row for row in rows if row["scope"] == "step")
    assert step_row["step_index"] == 2
    assert step_row["baseline"] == "send_with_confirmation"


def test_a_voyage_that_follows_the_defaults_raises_no_exception(tmp_path) -> None:
    rows = policy_exceptions(
        (
            {
                "voyage_id": "voyage_a",
                "name": "Ruhige Fahrt",
                "model_authority": "links_win",
                "rights": None,
                "steps": [{"workflow": "fact_distill", "rights": None}],
            },
        ),
        _store(tmp_path).list(),
    )

    assert rows == ()


# --------------------------------------------------------------------------- #
# The cleanup workflow consumes a bound policy, but never overrules the contract
# --------------------------------------------------------------------------- #


def test_a_bound_cleanup_policy_fills_in_empty_rules(tmp_path) -> None:
    store = _store(tmp_path)
    policy = store.save(
        {
            "name": "Ablage Standard",
            "form": "policy",
            "kind": "cleanup_rules",
            "statements": ["Text und Markdown wandern in den ersten Zielordner."],
            "body": {"rules": [{"suffixes": [".txt", ".md"], "target_root": 0}]},
        }
    )

    rules, origin = cleanup_rules_for_step((policy,), {"min_support": 2})

    assert rules == [{"suffixes": [".txt", ".md"], "target_root": 0}]
    assert origin == "policy Ablage Standard"


def test_rules_written_into_the_contract_win_over_a_bound_policy(tmp_path) -> None:
    policy = _store(tmp_path).save(
        {
            "name": "Ablage Standard",
            "form": "policy",
            "kind": "cleanup_rules",
            "statements": ["Text und Markdown wandern in den ersten Zielordner."],
            "body": {"rules": [{"suffixes": [".txt"], "target_root": 0}]},
        }
    )
    declared = [{"suffixes": [".pdf"], "target_root": 1}]

    rules, origin = cleanup_rules_for_step((policy,), {"rules": declared})

    assert rules == declared
    assert origin == "the job contract"


def test_no_bound_policy_leaves_the_step_untouched(tmp_path) -> None:
    rules, origin = cleanup_rules_for_step((), {})

    assert rules == []
    assert origin == "nothing"
