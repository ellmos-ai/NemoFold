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
