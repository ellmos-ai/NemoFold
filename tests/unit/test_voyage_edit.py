from __future__ import annotations

import pytest

from nemofold.voyage_edit import edit_to_primitive, plan_voyage_edit


def _voyage() -> dict:
    def step(workflow: str) -> dict:
        return {
            "workflow": workflow,
            "job": {
                "schema": "nemofold.job.v1",
                "workflow": workflow,
                "input_roots": ["documents"],
                "output_dir": "out",
                "questions": [],
                "privacy_mode": "local_only",
                "action_mode": "dry_run",
                "model_budget_usd": 0,
                "parameters": {},
            },
            "note": "",
            "reads_previous_output": False,
        }

    return {
        "voyage_id": "voyage_test",
        "name": "Unfallakte",
        "steps": [step("folder_digest"), step("fact_distill"), step("controlled_email")],
    }


def test_an_edit_is_a_proposal_and_never_a_write() -> None:
    edit = plan_voyage_edit("füge am Ende einen Tagesbericht ein", _voyage())

    payload = edit_to_primitive(edit)
    assert payload["applied"] is False
    assert payload["before"] == ["folder_digest", "fact_distill", "controlled_email"]
    assert payload["after"][-1] == "daily_arrivals"
    assert payload["changed"] is True


def test_a_position_between_two_steps_is_honoured() -> None:
    edit = plan_voyage_edit(
        "füge zwischen Schritt 2 und 3 eine Synopse ein", _voyage()
    )

    assert edit.action == "insert"
    assert list(edit.after) == [
        "folder_digest",
        "fact_distill",
        "synopsis_merge",
        "controlled_email",
    ]
    assert "as step 3" in edit.summary


@pytest.mark.parametrize(
    ("request_text", "expected_index"),
    [
        ("füge vor Schritt 1 eine Synopse ein", 0),
        ("füge nach Schritt 1 eine Synopse ein", 1),
        ("füge am Anfang eine Synopse ein", 0),
        ("füge eine Synopse ein", 3),
    ],
    ids=["before", "after", "start", "default-end"],
)
def test_every_position_phrase_lands_where_it_says(request_text, expected_index) -> None:
    edit = plan_voyage_edit(request_text, _voyage())

    assert edit.applicable is True
    assert list(edit.after).index("synopsis_merge") == expected_index


def test_a_proposed_step_starts_conservative() -> None:
    edit = plan_voyage_edit("füge eine Synopse am Ende ein", _voyage())

    proposed = edit.steps_after[-1]
    assert proposed["workflow"] == "synopsis_merge"
    assert proposed["job"]["action_mode"] == "dry_run"
    assert proposed["job"]["privacy_mode"] == "local_only"
    assert proposed["job"]["model_budget_usd"] == 0
    assert "review before running" in proposed["note"]


def test_removing_names_the_step_by_position_or_by_workflow() -> None:
    by_position = plan_voyage_edit("entferne Schritt 2", _voyage())
    assert by_position.action == "remove"
    assert list(by_position.after) == ["folder_digest", "controlled_email"]

    by_name = plan_voyage_edit("lösche den controlled_email Schritt", _voyage())
    assert list(by_name.after) == ["folder_digest", "fact_distill"]


def test_removing_the_last_remaining_step_is_refused() -> None:
    single = {"name": "x", "steps": [_voyage()["steps"][0]]}

    edit = plan_voyage_edit("entferne Schritt 1", single)

    assert edit.applicable is False
    assert edit.after == edit.before
    assert "at least one step" in " ".join(edit.notes)


def test_replacing_swaps_one_step_and_keeps_the_rest() -> None:
    edit = plan_voyage_edit("ersetze Schritt 1 durch eine Synopse", _voyage())

    assert edit.action == "replace"
    assert list(edit.after) == ["synopsis_merge", "fact_distill", "controlled_email"]
    assert "Replace step 1" in edit.summary


def test_renaming_needs_the_new_name_in_quotes() -> None:
    missing = plan_voyage_edit("benenne die Fahrt um", _voyage())
    assert missing.applicable is False
    assert "in quotes" in " ".join(missing.notes)

    named = plan_voyage_edit('benenne die Fahrt um in "Unfall 2026"', _voyage())
    assert named.action == "rename"
    assert named.new_name == "Unfall 2026"
    assert named.before == named.after  # renaming changes no step
    assert named.changed is True


def test_an_unmappable_step_is_explained_rather_than_invented() -> None:
    # Anonymization is part of every step's privacy gate, not a workflow.
    edit = plan_voyage_edit(
        "füge zwischen Schritt 2 und 3 einen Anonymisierungsschritt ein", _voyage()
    )

    assert edit.applicable is False
    assert edit.after == edit.before
    assert "privacy gate rather than a step of its own" in " ".join(edit.notes)


def test_a_planned_service_is_named_as_planned() -> None:
    edit = plan_voyage_edit("füge einen Schritt für bilingual sync ein", _voyage())

    assert edit.applicable is False
    assert "planned service" in edit.summary
    assert any("Bilingual sync" in note for note in edit.notes)


def test_an_unrecognised_request_says_what_editing_understands() -> None:
    edit = plan_voyage_edit("mach das irgendwie besser", _voyage())

    assert edit.action == "none"
    assert edit.applicable is False
    assert "inserting, removing, replacing and renaming" in " ".join(edit.notes)


def test_an_empty_request_is_refused() -> None:
    with pytest.raises(ValueError):
        plan_voyage_edit("   ", _voyage())
