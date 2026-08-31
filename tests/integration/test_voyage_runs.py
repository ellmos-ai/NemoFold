from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig
from nemofold.voyage_runs import LOCAL_CORE, resolve_model, run_voyage
from nemofold.voyages import LOCAL_ONLY, VoyageStore

NOTE_A = """Vertragsstand April
Die Deckung beginnt am 1. April 2026.
Der Beitrag betraegt 148 Euro pro Jahr.
"""


def _corpus(tmp_path: Path) -> Path:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "police.txt").write_text(NOTE_A, encoding="utf-8")
    return documents


def _chain(tmp_path: Path, documents: Path, **step_two) -> dict:
    return {
        "name": "Faktenlage",
        "steps": [
            {
                "workflow": "fact_distill",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "fact_distill",
                    "input_roots": [str(documents)],
                    "output_dir": str(tmp_path / "out" / "01-facts"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"dedupe_scope": "normalized", "formats": ["md"]},
                },
            },
            {
                "workflow": "folder_digest",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(documents)],
                    "output_dir": str(tmp_path / "out" / "02-digest"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {},
                },
                **step_two,
            },
        ],
    }


def test_a_chain_runs_its_steps_and_writes_one_dossier(tmp_path) -> None:
    documents = _corpus(tmp_path)
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    voyage = store.save(_chain(tmp_path, documents))

    result = run_voyage(
        voyage,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="chain_ok",
        base_dir=tmp_path,
    )

    assert result.status == "executed"
    assert result.completed is True
    assert [step.workflow for step in result.steps] == ["fact_distill", "folder_digest"]
    assert [step.run_id for step in result.steps] == ["chain_ok_01", "chain_ok_02"]
    assert all(step.status == "executed" for step in result.steps)
    assert all(step.artifact_count >= 1 for step in result.steps)

    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    assert dossier["schema"] == "nemofold.voyage-run.v1"
    assert dossier["completed"] is True
    assert dossier["cloud_proof"] is False
    # The dossier links each step's own ledger rather than replacing it.
    for step in dossier["steps"]:
        assert Path(step["ledger_path"]).is_file()

    markdown = Path(result.dossier_path).with_suffix(".md").read_text(encoding="utf-8")
    assert "# Voyage dossier · Faktenlage" in markdown
    assert "Step 1 · fact_distill" in markdown


def test_a_declared_handoff_feeds_output_into_the_next_step(tmp_path) -> None:
    documents = _corpus(tmp_path)
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    voyage = store.save(_chain(tmp_path, documents, reads_previous_output=True))

    result = run_voyage(
        voyage,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="chain_handoff",
        base_dir=tmp_path,
    )

    assert result.status == "executed"
    ledger = json.loads(Path(result.steps[1].ledger_path or "").read_text(encoding="utf-8"))
    # The digest read the first step's output directory, as the plan declared.
    assert ledger["gate_decision"]["allowed"] is True
    assert result.steps[0].output_dir == str(tmp_path / "out" / "01-facts")


def test_the_handoff_must_be_declared_in_the_plan_not_guessed(tmp_path) -> None:
    documents = _corpus(tmp_path)
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    voyage = store.save(_chain(tmp_path, documents))

    assert voyage["steps"][1]["reads_previous_output"] is False
    with pytest.raises(ValueError, match="first step has no previous output"):
        store.save(
            {
                "name": "x",
                "steps": [
                    {**_chain(tmp_path, documents)["steps"][0], "reads_previous_output": True}
                ],
            }
        )


def test_a_blocked_step_stops_the_chain_and_says_where(tmp_path) -> None:
    documents = _corpus(tmp_path)
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    chain = _chain(tmp_path, documents)
    # An action step without the server-side gate must block, not run.
    chain["steps"][0]["job"]["workflow"] = "smart_inbox"
    chain["steps"][0]["workflow"] = "smart_inbox"
    chain["steps"][0]["job"]["action_mode"] = "apply"
    chain["steps"][0]["job"]["target_roots"] = [str(tmp_path / "archive")]
    chain["steps"][0]["job"]["parameters"] = {
        "classification_policy": "suffix_routes",
        "routes": [{"suffixes": [".txt"], "target_root": 0}],
        "allowed_extensions": [".txt"],
        "original_policy": "move",
    }
    voyage = store.save(chain)

    result = run_voyage(
        voyage,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="chain_blocked",
        base_dir=tmp_path,
    )

    assert result.status == "stopped"
    assert result.completed is False
    assert result.stopped_at == 1
    # The later step was never started, so nothing ran on an unfinished result.
    assert len(result.steps) == 1
    assert result.steps[0].status != "executed"

    markdown = Path(result.dossier_path).with_suffix(".md").read_text(encoding="utf-8")
    assert "The chain stopped at step 1" in markdown
    assert "Later steps were not started" in markdown


def test_the_dossier_names_the_model_that_actually_ran(tmp_path) -> None:
    documents = _corpus(tmp_path)
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    chain = _chain(tmp_path, documents)
    chain["steps"][0]["model_pref"] = {
        "preferred": {"provider": "openai", "model": "gpt-4o-mini"},
        "fallback": LOCAL_ONLY,
    }
    voyage = store.save(chain)

    result = run_voyage(
        voyage,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="chain_model",
        base_dir=tmp_path,
    )

    step = result.steps[0]
    # The preference did not run. The dossier says what did, and why.
    assert step.model_used == LOCAL_CORE
    assert "was not applied" in step.model_note
    assert "per-run approval" in step.model_note
    assert "lowers exposure" in step.model_note

    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    assert dossier["steps"][0]["model_used"] == LOCAL_CORE


def test_an_allowed_external_preference_still_does_not_escalate_a_chain() -> None:
    pref = {
        "preferred": {"provider": "openai", "model": "gpt-4o-mini"},
        "fallback": LOCAL_ONLY,
    }

    used, note = resolve_model(pref, external_allowed=True)

    # Even with the server gate open, a chained step does not raise exposure.
    assert used == LOCAL_CORE
    assert "raising exposure is never automatic" in note
    assert "fallback is local-only" in note


def test_no_preference_is_reported_as_such() -> None:
    used, note = resolve_model(None, external_allowed=False)
    assert used == LOCAL_CORE
    assert "No model preference" in note


def test_an_empty_voyage_cannot_be_run(tmp_path) -> None:
    with pytest.raises(ValueError, match="no step to run"):
        run_voyage(
            {"voyage_id": "voyage_x", "name": "x", "steps": []},
            ExecutionConfig(allowed_roots=(str(tmp_path),)),
            run_id="chain_empty",
            base_dir=tmp_path,
        )
