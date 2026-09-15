from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.voyages import (
    LOCAL_ONLY,
    VOYAGE_SCHEMA,
    VoyageStore,
    load_presets,
    validate_model_pref,
)


def _store(tmp_path: Path) -> VoyageStore:
    return VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))


def _voyage(tmp_path: Path, **overrides) -> dict:
    documents = tmp_path / "documents"
    documents.mkdir(exist_ok=True)
    payload = {
        "name": "Faktenlage Unfall",
        "description": "Zwei Schritte für den Versicherungsfall.",
        "steps": [
            {
                "workflow": "fact_distill",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "fact_distill",
                    "input_roots": [str(documents)],
                    "output_dir": str(tmp_path / "out" / "01"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"dedupe_scope": "normalized", "formats": ["md"]},
                },
                "note": "Erst die Fakten.",
            }
        ],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Library
# --------------------------------------------------------------------------- #


def test_a_voyage_is_saved_loaded_and_listed(tmp_path) -> None:
    store = _store(tmp_path)

    saved = store.save(_voyage(tmp_path))

    assert saved["schema"] == VOYAGE_SCHEMA
    assert saved["voyage_id"].startswith("voyage_")
    assert saved["source"] == "manual"
    assert saved["steps"][0]["workflow"] == "fact_distill"
    # Approvals never travel with a saved plan.
    assert saved["approval_state"]["external_transfer"] is False
    assert saved["approval_state"]["file_actions"] is False

    assert store.load(saved["voyage_id"])["name"] == "Faktenlage Unfall"
    listed = {item["voyage_id"]: item for item in store.list()}
    assert listed[saved["voyage_id"]]["step_count"] == 1
    assert listed[saved["voyage_id"]]["editable"] is True


def test_loading_a_saved_voyage_rejects_a_tampered_handoff_edge(tmp_path) -> None:
    store = _store(tmp_path)
    plan = _voyage(tmp_path)
    second = json.loads(json.dumps(plan["steps"][0]))
    second["job"]["output_dir"] = str(tmp_path / "out" / "02")
    second["handoff"] = {"format": "markdown"}
    plan["steps"].append(second)
    saved = store.save(plan)
    path = store.root / f"{saved['voyage_id']}.json"
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["steps"][1]["reads_previous_output"] = True
    path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(ValueError, match="stored step contract invalid"):
        store.load(saved["voyage_id"])


def test_saved_receipt_rejects_valid_looking_top_level_rights_tamper(tmp_path) -> None:
    store = _store(tmp_path)
    saved = store.save(_voyage(tmp_path))
    path = store.root / f"{saved['voyage_id']}.json"
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["rights"] = "send_when_ordered"
    changed["model_authority"] = "chain_wins"
    path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(ValueError, match="voyage receipt hash mismatch"):
        store.load(saved["voyage_id"])


def test_unreceipted_legacy_voyage_can_be_read_but_not_executed(tmp_path) -> None:
    store = _store(tmp_path)
    saved = store.save(_voyage(tmp_path))
    receipt = store.root / "_receipts" / f"{saved['voyage_id']}.json"
    assert receipt.is_file()
    receipt.unlink()

    assert store.load(saved["voyage_id"])["name"] == "Faktenlage Unfall"
    with pytest.raises(ValueError, match="voyage receipt missing"):
        store.load(saved["voyage_id"], require_receipt=True)


def test_saving_with_an_id_updates_and_keeps_the_creation_time(tmp_path) -> None:
    store = _store(tmp_path)
    first = store.save(_voyage(tmp_path))

    second = store.save(
        _voyage(tmp_path, voyage_id=first["voyage_id"], name="Faktenlage Unfall v2")
    )

    assert second["voyage_id"] == first["voyage_id"]
    assert second["name"] == "Faktenlage Unfall v2"
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] >= first["updated_at"]


def test_a_step_outside_the_allow_roots_is_refused(tmp_path) -> None:
    store = _store(tmp_path)
    voyage = _voyage(tmp_path)
    voyage["steps"][0]["job"]["input_roots"] = [str(tmp_path.parent / "elsewhere")]

    with pytest.raises(PermissionError, match="outside the configured allow roots"):
        store.save(voyage)


def test_an_empty_or_oversized_voyage_is_refused(tmp_path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="at least one step"):
        store.save(_voyage(tmp_path, steps=[]))
    with pytest.raises(ValueError, match="unknown voyage field"):
        store.save(_voyage(tmp_path, colour="blue"))


def test_delete_removes_own_entries_but_never_a_preset(tmp_path) -> None:
    store = _store(tmp_path)
    saved = store.save(_voyage(tmp_path))

    store.delete(saved["voyage_id"])
    assert all(item["voyage_id"] != saved["voyage_id"] for item in store.list())

    with pytest.raises(PermissionError, match="read-only sources"):
        store.delete("preset_fact_digest_pdf")


# --------------------------------------------------------------------------- #
# Shipped specialists
# --------------------------------------------------------------------------- #


def test_presets_ship_with_the_package_and_only_use_active_workflows() -> None:
    from nemofold.job_io import SUPPORTED_WORKFLOWS

    presets = load_presets()

    assert len(presets) >= 4
    ids = {preset["preset_id"] for preset in presets}
    assert "preset_fact_digest_pdf" in ids
    assert "preset_daily_arrivals" in ids
    for preset in presets:
        assert preset["description"].strip()
        assert preset["steps"]
        for step in preset["steps"]:
            assert step["workflow"] in SUPPORTED_WORKFLOWS
            # A preset carries no path: it cannot name a folder on someone
            # else's machine, and it therefore cannot run by itself.
            assert "job" not in step
            assert "input_roots" not in step.get("parameters", {})


def test_presets_are_listed_as_read_only_next_to_saved_voyages(tmp_path) -> None:
    store = _store(tmp_path)
    store.save(_voyage(tmp_path))

    listed = store.list()
    shipped = [item for item in listed if item["source"] == "preset" and not item["editable"]]

    assert len(shipped) == len(load_presets())
    assert all(item["voyage_id"].startswith("preset_") for item in shipped)
    assert any(item["editable"] for item in listed)


def test_copying_a_preset_binds_it_to_your_own_folders(tmp_path) -> None:
    store = _store(tmp_path)
    documents = tmp_path / "documents"
    documents.mkdir()

    copied = store.copy_preset(
        "preset_fact_digest_pdf",
        input_roots=(str(documents),),
        output_dir=str(tmp_path / "out"),
        name="Meine Faktenlage",
    )

    assert copied["source"] == "preset"
    assert copied["name"] == "Meine Faktenlage"
    step = copied["steps"][0]
    assert step["job"]["input_roots"] == [str(documents)]
    # A copied preset starts conservative no matter what it does later.
    assert step["job"]["action_mode"] == "dry_run"
    assert step["job"]["privacy_mode"] == "local_only"
    assert step["job"]["model_budget_usd"] == 0
    # And it is a normal, editable library entry now.
    assert store.load(copied["voyage_id"])["voyage_id"] == copied["voyage_id"]


def test_copying_a_preset_needs_an_approved_root(tmp_path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="at least one approved input root"):
        store.copy_preset(
            "preset_fact_digest_pdf", input_roots=(), output_dir=str(tmp_path / "out")
        )
    with pytest.raises(ValueError, match="preset does not exist"):
        store.copy_preset(
            "preset_unknown_case",
            input_roots=(str(tmp_path),),
            output_dir=str(tmp_path / "out"),
        )


def test_a_copied_preset_is_a_plan_not_a_run(tmp_path) -> None:
    store = _store(tmp_path)
    documents = tmp_path / "documents"
    documents.mkdir()

    copied = store.copy_preset(
        "preset_topic_bundle_pdf",
        input_roots=(str(documents),),
        output_dir=str(tmp_path / "out"),
    )

    # Two steps prepared, no ledger, no artifact, nothing executed.
    assert [step["workflow"] for step in copied["steps"]] == [
        "bundle_export",
        "evidence_analyst",
    ]
    assert not (tmp_path / "out" / "ledger").exists()


# --------------------------------------------------------------------------- #
# Model preference
# --------------------------------------------------------------------------- #


def test_a_fallback_may_lower_exposure(tmp_path) -> None:
    resolved = validate_model_pref(
        {
            "preferred": {"provider": "openai", "model": "gpt-4o-mini"},
            "fallback": {"provider": "ollama", "model": "qwen3"},
        }
    )

    assert resolved is not None
    assert resolved["preferred"]["provider"] == "openai"
    assert resolved["fallback"]["provider"] == "ollama"


def test_a_fallback_may_never_raise_exposure() -> None:
    with pytest.raises(ValueError, match="only lower exposure"):
        validate_model_pref(
            {
                "preferred": {"provider": "ollama", "model": "qwen3"},
                "fallback": {"provider": "openai", "model": "gpt-4o-mini"},
            }
        )


def test_local_only_is_the_default_fallback() -> None:
    resolved = validate_model_pref(
        {"preferred": {"provider": "anthropic", "model": "claude-sonnet-4-5"}}
    )

    assert resolved is not None
    assert resolved["fallback"] == LOCAL_ONLY
    assert validate_model_pref(None) is None


def test_model_preference_is_stored_per_step(tmp_path) -> None:
    store = _store(tmp_path)
    voyage = _voyage(tmp_path)
    voyage["steps"][0]["model_pref"] = {
        "preferred": {"provider": "openai", "model": "gpt-4o-mini"},
        "fallback": LOCAL_ONLY,
    }

    saved = store.save(voyage)

    stored = saved["steps"][0]["model_pref"]
    assert stored["preferred"] == {"provider": "openai", "model": "gpt-4o-mini"}
    assert stored["fallback"] == LOCAL_ONLY
    # Storing a preference grants nothing: the run still starts local and closed.
    assert saved["steps"][0]["job"]["privacy_mode"] == "local_only"
    assert saved["approval_state"]["external_transfer"] is False


def test_unknown_providers_and_fields_are_refused() -> None:
    with pytest.raises(ValueError, match="preferred provider is unsupported"):
        validate_model_pref({"preferred": {"provider": "nebius-direct", "model": "x"}})
    with pytest.raises(ValueError, match="only carry preferred and fallback"):
        validate_model_pref(
            {"preferred": {"provider": "ollama", "model": "qwen3"}, "always": True}
        )


def test_the_library_file_is_readable_json_on_disk(tmp_path) -> None:
    store = _store(tmp_path)
    saved = store.save(_voyage(tmp_path))

    path = tmp_path / "run-reports" / "web-console" / "voyages" / f"{saved['voyage_id']}.json"
    value = json.loads(path.read_text(encoding="utf-8"))

    assert value["schema"] == VOYAGE_SCHEMA
    assert value["steps"][0]["note"] == "Erst die Fakten."


# --------------------------------------------------------------------------- #
# Reservations, chain authority, rights and policy references
# --------------------------------------------------------------------------- #


def test_a_wanted_but_impossible_use_case_is_kept_as_a_reservation(tmp_path) -> None:
    store = _store(tmp_path)

    saved = store.save(
        _voyage(
            tmp_path,
            name="Marktrecherche zum Anbieter",
            status="pending_capability",
            missing_capability="web_research",
        )
    )

    assert saved["status"] == "pending_capability"
    assert saved["missing_capability"] == "web_research"
    listed = next(
        item for item in store.list() if item["voyage_id"] == saved["voyage_id"]
    )
    assert listed["status"] == "pending_capability"
    assert listed["missing_capability"] == "web_research"


def test_a_reservation_must_name_what_it_waits_for(tmp_path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="must name the missing capability"):
        store.save(_voyage(tmp_path, status="pending_capability"))
    with pytest.raises(ValueError, match="cannot wait for a missing capability"):
        store.save(_voyage(tmp_path, missing_capability="web_research"))


def test_a_reservation_becomes_runnable_by_clearing_the_missing_piece(tmp_path) -> None:
    store = _store(tmp_path)
    reserved = store.save(
        _voyage(tmp_path, status="pending_capability", missing_capability="web_research")
    )

    freed = store.save(
        _voyage(tmp_path, voyage_id=reserved["voyage_id"], status="runnable")
    )

    assert freed["status"] == "runnable"
    assert freed["missing_capability"] == ""


def test_a_chain_that_overrides_its_links_is_flagged_with_its_reason(tmp_path) -> None:
    store = _store(tmp_path)

    saved = store.save(
        _voyage(
            tmp_path,
            model_authority="chain_wins",
            model_pref={"preferred": {"provider": "ollama", "model": "qwen3"}},
            authority_reason="Datenschutzkritisch: laeuft immer lokal.",
        )
    )

    assert saved["model_authority"] == "chain_wins"
    assert saved["authority_reason"].startswith("Datenschutzkritisch")
    listed = next(item for item in store.list() if item["voyage_id"] == saved["voyage_id"])
    assert listed["overrides_links"] is True
    assert listed["authority_reason"].startswith("Datenschutzkritisch")


def test_an_overriding_chain_with_an_external_model_needs_confirmation_when_set(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    external = {
        "model_authority": "chain_wins",
        "model_pref": {"preferred": {"provider": "openai", "model": "gpt-4o-mini"}},
    }

    with pytest.raises(ValueError, match="confirmed at set time"):
        store.save(_voyage(tmp_path, **external))

    confirmed = store.save(
        _voyage(tmp_path, confirm_external_authority=True, **external)
    )
    assert confirmed["model_authority"] == "chain_wins"
    # The confirmation authorises the setting, never a transfer.
    assert confirmed["approval_state"]["external_transfer"] is False


def test_a_local_chain_that_overrides_needs_no_confirmation(tmp_path) -> None:
    store = _store(tmp_path)

    saved = store.save(
        _voyage(
            tmp_path,
            model_authority="chain_wins",
            model_pref={"preferred": {"provider": "ollama", "model": "qwen3"}},
        )
    )

    assert saved["model_authority"] == "chain_wins"


def test_a_chain_can_declare_itself_local_only(tmp_path) -> None:
    store = _store(tmp_path)

    saved = store.save(_voyage(tmp_path, model_pref=LOCAL_ONLY))

    assert saved["model_pref"] == LOCAL_ONLY


def test_rights_and_policy_references_are_carried_on_both_levels(tmp_path) -> None:
    store = _store(tmp_path)
    voyage = _voyage(tmp_path, rights="send_with_confirmation", policy_refs=["gdpr_basic"])
    voyage["steps"][0]["rights"] = "draft_only"
    voyage["steps"][0]["policy_refs"] = ["gdpr_basic", "insurance_case"]

    saved = store.save(voyage)

    assert saved["rights"] == "send_with_confirmation"
    assert saved["policy_refs"] == ["gdpr_basic"]
    assert saved["steps"][0]["rights"] == "draft_only"
    assert saved["steps"][0]["policy_refs"] == ["gdpr_basic", "insurance_case"]


def test_rights_and_policy_references_default_to_nothing(tmp_path) -> None:
    saved = _store(tmp_path).save(_voyage(tmp_path))

    assert saved["rights"] is None
    assert saved["policy_refs"] == []
    assert saved["steps"][0]["rights"] is None
    assert saved["steps"][0]["policy_refs"] == []


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("rights", "send_anything", "draft_only"),
        ("policy_refs", ["a", "a"], "must not repeat"),
        ("policy_refs", "gdpr", "must be a list"),
        ("status", "someday", "runnable or pending_capability"),
        ("model_authority", "steps_win", "links_win or chain_wins"),
    ],
)
def test_the_new_fields_refuse_unusable_values(tmp_path, field, value, message) -> None:
    with pytest.raises(ValueError, match=message):
        _store(tmp_path).save(_voyage(tmp_path, **{field: value}))


# --------------------------------------------------------------------------- #
# Tags and schedules: how a use case finds its room
# --------------------------------------------------------------------------- #


def test_tags_are_normalised_and_sorted(tmp_path) -> None:
    saved = _store(tmp_path).save(
        _voyage(tmp_path, tags=["Reporting", "document-analysis", "reporting"])
    )

    assert saved["tags"] == ["document-analysis", "reporting"]


def test_a_schedule_derives_the_scheduled_tag(tmp_path) -> None:
    saved = _store(tmp_path).save(
        _voyage(
            tmp_path,
            tags=["folder-watch"],
            schedule={"cadence": "daily", "at": "07:00"},
        )
    )

    assert saved["tags"] == ["folder-watch", "scheduled"]
    assert saved["schedule"]["cadence"] == "daily"
    # The stored object says it for itself: a saved routine is an intention.
    assert saved["schedule"]["installed_by_nemofold"] is False


def test_the_scheduled_tag_cannot_be_claimed_by_hand(tmp_path) -> None:
    with pytest.raises(ValueError, match="derived from the schedule field"):
        _store(tmp_path).save(_voyage(tmp_path, tags=["scheduled"]))


@pytest.mark.parametrize(
    ("schedule", "message"),
    [
        ({"cadence": "hourly", "at": "07:00"}, "daily, weekly or monthly"),
        ({"cadence": "daily", "at": "25:00"}, "24-hour"),
        ({"cadence": "daily", "at": "7:00"}, "24-hour"),
        ({"cadence": "daily", "every": 2}, "cadence, at and note"),
    ],
)
def test_a_schedule_refuses_unusable_values(tmp_path, schedule, message) -> None:
    with pytest.raises(ValueError, match=message):
        _store(tmp_path).save(_voyage(tmp_path, schedule=schedule))


def test_dropping_the_schedule_drops_the_derived_tag(tmp_path) -> None:
    store = _store(tmp_path)
    saved = store.save(
        _voyage(tmp_path, tags=["folder-watch"], schedule={"cadence": "daily", "at": "07:00"})
    )

    cleared = store.save(_voyage(tmp_path, voyage_id=saved["voyage_id"], schedule=None))

    assert cleared["tags"] == ["folder-watch"]
    assert cleared["schedule"] is None


# --------------------------------------------------------------------------- #
# A partial update must not erase what it did not mention
# --------------------------------------------------------------------------- #


def test_reordering_steps_keeps_the_fields_the_request_omitted(tmp_path) -> None:
    store = _store(tmp_path)
    saved = store.save(
        _voyage(
            tmp_path,
            source="preset",
            tags=["document-analysis"],
            schedule={"cadence": "weekly", "at": "18:30"},
            rights="send_with_confirmation",
            policy_refs=["gdpr_basic"],
        )
    )

    # What the browser sends when someone only moves a step: id, name, steps.
    updated = store.save(
        {
            "voyage_id": saved["voyage_id"],
            "name": saved["name"],
            "steps": [dict(step) for step in saved["steps"]],
        }
    )

    assert updated["tags"] == ["document-analysis", "scheduled"]
    assert updated["schedule"]["at"] == "18:30"
    assert updated["rights"] == "send_with_confirmation"
    assert updated["policy_refs"] == ["gdpr_basic"]
    assert updated["source"] == "preset"
    assert updated["description"] == saved["description"]
    assert updated["created_at"] == saved["created_at"]


def test_a_reservation_stays_a_reservation_across_a_partial_save(tmp_path) -> None:
    store = _store(tmp_path)
    saved = store.save(
        _voyage(tmp_path, status="pending_capability", missing_capability="chat_delivery")
    )

    updated = store.save(
        {"voyage_id": saved["voyage_id"], "name": "Neuer Name", "steps": saved["steps"]}
    )

    assert updated["status"] == "pending_capability"
    assert updated["missing_capability"] == "chat_delivery"


def test_an_unchanged_external_chain_authority_needs_no_new_confirmation(tmp_path) -> None:
    store = _store(tmp_path)
    saved = store.save(
        _voyage(
            tmp_path,
            model_authority="chain_wins",
            model_pref={"preferred": {"provider": "openai", "model": "gpt-5.4"}},
            confirm_external_authority=True,
        )
    )

    # Re-saving the same setting is not setting it, so it asks nobody again.
    updated = store.save(
        {"voyage_id": saved["voyage_id"], "name": saved["name"], "steps": saved["steps"]}
    )

    assert updated["model_authority"] == "chain_wins"
    assert updated["model_pref"]["preferred"]["provider"] == "openai"


def test_changing_to_a_different_external_chain_model_asks_again(tmp_path) -> None:
    store = _store(tmp_path)
    saved = store.save(
        _voyage(
            tmp_path,
            model_authority="chain_wins",
            model_pref={"preferred": {"provider": "openai", "model": "gpt-5.4"}},
            confirm_external_authority=True,
        )
    )

    with pytest.raises(ValueError, match="confirmed at set time"):
        store.save(
            {
                "voyage_id": saved["voyage_id"],
                "name": saved["name"],
                "steps": saved["steps"],
                "model_pref": {"preferred": {"provider": "openai", "model": "gpt-5.5"}},
            }
        )


def test_a_copied_specialist_keeps_the_room_it_belongs_to(tmp_path) -> None:
    store = _store(tmp_path)
    documents = tmp_path / "documents"
    documents.mkdir(exist_ok=True)

    copied = store.copy_preset(
        "preset_daily_arrivals",
        input_roots=(str(documents),),
        output_dir=str(tmp_path / "out"),
    )

    assert "folder-watch" in copied["tags"]
    assert "scheduled" in copied["tags"]
    assert copied["schedule"]["cadence"] == "daily"


def test_every_shipped_specialist_carries_at_least_one_tag() -> None:
    listed = load_presets()

    assert listed
    for preset in listed:
        assert preset.get("tags"), preset["preset_id"]


# --------------------------------------------------------------------------- #
# Exposure means "does it leave this host", not "does it need a key"
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bridge", ["codex-cli", "claude-code"])
def test_a_fallback_to_a_subscription_bridge_is_refused(bridge) -> None:
    # These carry no API key of their own and still put the content on somebody
    # else's machine, so falling back to one from a local model raises exposure.
    with pytest.raises(ValueError, match="only lower exposure"):
        validate_model_pref(
            {
                "preferred": {"provider": "ollama", "model": "qwen3"},
                "fallback": {"provider": bridge, "model": "sonnet"},
            }
        )


def test_a_local_only_chain_treats_a_subscription_bridge_as_external(tmp_path) -> None:
    store = _store(tmp_path)

    saved = store.save(
        _voyage(
            tmp_path,
            model_pref=LOCAL_ONLY,
            steps=_voyage(tmp_path)["steps"],
        )
    )
    assert saved["model_pref"] == LOCAL_ONLY

    from nemofold.model_authority import resolve_authority

    resolution = resolve_authority(
        step_pref={
            "preferred": {"provider": "claude-code", "model": "sonnet"},
            "fallback": LOCAL_ONLY,
        },
        chain_pref=LOCAL_ONLY,
    )

    assert resolution.needs_user_input is True
    assert resolution.conflict == "local_only_cap"


@pytest.mark.parametrize("bridge", ["codex-cli", "claude-code"])
def test_chain_wins_with_a_subscription_bridge_is_confirmed_at_set_time(tmp_path, bridge) -> None:
    with pytest.raises(ValueError, match="confirmed at set time"):
        _store(tmp_path).save(
            _voyage(
                tmp_path,
                model_authority="chain_wins",
                model_pref={
                    "preferred": {"provider": bridge, "model": "sonnet"},
                    "fallback": LOCAL_ONLY,
                },
            )
        )
