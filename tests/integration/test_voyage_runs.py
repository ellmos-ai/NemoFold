from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig
from nemofold.model_authority import (
    AUTHORITY_CHAIN_WINS,
    LEVEL_CHAIN,
    LEVEL_LINK,
    LEVEL_RUN_OVERRIDE,
    LOCAL_CORE,
)
from nemofold.policies import PolicyStore
from nemofold.voyage_runs import run_voyage
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


def test_the_dossier_names_the_model_and_the_level_that_decided(tmp_path) -> None:
    documents = _corpus(tmp_path)
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    chain = _chain(tmp_path, documents)
    chain["steps"][0]["model_pref"] = {
        "preferred": {"provider": "ollama", "model": "qwen3"},
        "fallback": LOCAL_ONLY,
    }
    voyage = store.save(chain)

    result = run_voyage(
        voyage,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="chain_model",
        base_dir=tmp_path,
    )

    first, second = result.steps
    assert first.model_used == "ollama:qwen3"
    assert first.model_level == LEVEL_LINK
    assert "link level" in first.model_note
    # The step without a preference falls back to the local default.
    assert second.model_used == LOCAL_CORE
    assert second.model_level == "default"

    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    assert dossier["steps"][0]["model_level"] == LEVEL_LINK
    assert dossier["model_authority"] == "links_win"
    assert dossier["run_level_override"] is None

    markdown = Path(result.dossier_path).with_suffix(".md").read_text(encoding="utf-8")
    assert "level: link" in markdown
    assert "outbound rights: draft_only" in markdown


def test_a_chain_that_overrides_its_links_says_so_in_the_dossier(tmp_path) -> None:
    documents = _corpus(tmp_path)
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    chain = _chain(tmp_path, documents)
    chain["steps"][0]["model_pref"] = {
        "preferred": {"provider": "lm-studio", "model": "mistral"},
        "fallback": LOCAL_ONLY,
    }
    chain["model_pref"] = {
        "preferred": {"provider": "ollama", "model": "qwen3"},
        "fallback": LOCAL_ONLY,
    }
    chain["model_authority"] = AUTHORITY_CHAIN_WINS
    chain["authority_reason"] = "Datenschutzkritisch: laeuft immer lokal."
    voyage = store.save(chain)

    result = run_voyage(
        voyage,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="chain_authority",
        base_dir=tmp_path,
    )

    first = result.steps[0]
    assert first.model_used == "ollama:qwen3"
    assert first.model_level == LEVEL_CHAIN
    assert "overrides this step's own setting" in first.model_note
    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    assert dossier["model_authority"] == AUTHORITY_CHAIN_WINS
    assert dossier["authority_reason"] == "Datenschutzkritisch: laeuft immer lokal."


def test_a_run_level_override_applies_once_and_changes_nothing_stored(tmp_path) -> None:
    documents = _corpus(tmp_path)
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    chain = _chain(tmp_path, documents)
    chain["steps"][0]["model_pref"] = {
        "preferred": {"provider": "ollama", "model": "qwen3"},
        "fallback": LOCAL_ONLY,
    }
    voyage = store.save(chain)

    result = run_voyage(
        voyage,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="chain_override",
        base_dir=tmp_path,
        model_override={"provider": "lm-studio", "model": "mistral"},
    )

    assert all(step.model_used == "lm-studio:mistral" for step in result.steps)
    assert all(step.model_level == LEVEL_RUN_OVERRIDE for step in result.steps)
    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    assert dossier["run_level_override"] == "lm-studio:mistral"

    # The stored voyage is untouched by the one-off choice.
    stored = store.load(voyage["voyage_id"])
    assert stored["steps"][0]["model_pref"]["preferred"]["provider"] == "ollama"


def test_a_local_only_cap_stops_the_chain_instead_of_escalating(tmp_path) -> None:
    documents = _corpus(tmp_path)
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    chain = _chain(tmp_path, documents)
    chain["model_pref"] = LOCAL_ONLY
    chain["steps"][0]["model_pref"] = {
        "preferred": {"provider": "openai", "model": "gpt-4o-mini"},
        "fallback": LOCAL_ONLY,
    }
    voyage = store.save(chain)

    result = run_voyage(
        voyage,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="chain_capped",
        base_dir=tmp_path,
    )

    assert result.status == "needs_user_input"
    assert result.stopped_at == 1
    step = result.steps[0]
    assert step.status == "needs_user_input"
    assert step.errors == ("local_only_cap",)
    assert step.ledger_path is None  # nothing ran
    assert step.artifact_count == 0

    markdown = Path(result.dossier_path).with_suffix(".md").read_text(encoding="utf-8")
    assert "conflicts with the chain's local-only cap" in markdown
    assert "needs your decision" in markdown


def test_the_cap_also_holds_against_a_run_level_override(tmp_path) -> None:
    documents = _corpus(tmp_path)
    store = VoyageStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    chain = _chain(tmp_path, documents)
    chain["model_pref"] = LOCAL_ONLY
    voyage = store.save(chain)

    result = run_voyage(
        voyage,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="chain_capped_override",
        base_dir=tmp_path,
        model_override={"provider": "anthropic", "model": "claude-sonnet-4-5"},
    )

    assert result.status == "needs_user_input"
    assert result.steps[0].errors == ("local_only_cap",)


def test_an_empty_voyage_cannot_be_run(tmp_path) -> None:
    with pytest.raises(ValueError, match="no step to run"):
        run_voyage(
            {"voyage_id": "voyage_x", "name": "x", "steps": []},
            ExecutionConfig(allowed_roots=(str(tmp_path),)),
            run_id="chain_empty",
            base_dir=tmp_path,
        )


def test_a_bound_cleanup_policy_reaches_the_step_and_the_dossier(tmp_path) -> None:
    documents = _corpus(tmp_path)
    archive = tmp_path / "archive"
    archive.mkdir()
    roots = (str(tmp_path),)
    policy_store = PolicyStore(base_dir=tmp_path, allowed_roots=roots)
    policy = policy_store.save(
        {
            "name": "Ablage Standard",
            "form": "policy",
            "kind": "cleanup_rules",
            "statements": ["Text und Markdown wandern in den Archivordner."],
            "body": {"rules": [{"suffixes": [".txt"], "target_root": 0}]},
        }
    )
    voyage = VoyageStore(base_dir=tmp_path, allowed_roots=roots).save(
        {
            "name": "Aufräumen nach Regelwerk",
            "steps": [
                {
                    "workflow": "cleanup_rules",
                    "job": {
                        "schema": "nemofold.job.v1",
                        "workflow": "cleanup_rules",
                        "input_roots": [str(documents)],
                        "target_roots": [str(archive)],
                        "output_dir": str(tmp_path / "out" / "01-cleanup"),
                        "privacy_mode": "local_only",
                        "action_mode": "dry_run",
                        "parameters": {"allowed_extensions": [".txt"]},
                    },
                }
            ],
        }
    )
    policy_store.bind(
        policy["policy_id"], target="voyage", voyage_id=voyage["voyage_id"]
    )

    result = run_voyage(
        voyage,
        ExecutionConfig(allowed_roots=roots),
        run_id="run_policy_bound",
        base_dir=tmp_path,
        policy_store=policy_store,
    )

    assert result.status == "executed"
    assert result.steps[0].policy_note == "Cleanup rules came from policy Ablage Standard."
    dossier = json.loads(Path(result.dossier_path).read_text(encoding="utf-8"))
    assert dossier["steps"][0]["policy_note"].endswith("policy Ablage Standard.")
    markdown = Path(result.dossier_path).with_suffix(".md").read_text(encoding="utf-8")
    assert "Ablage Standard" in markdown


def test_rules_in_the_contract_are_not_replaced_by_a_bound_policy(tmp_path) -> None:
    documents = _corpus(tmp_path)
    archive = tmp_path / "archive"
    archive.mkdir()
    roots = (str(tmp_path),)
    policy_store = PolicyStore(base_dir=tmp_path, allowed_roots=roots)
    policy = policy_store.save(
        {
            "name": "Ablage Standard",
            "form": "policy",
            "kind": "cleanup_rules",
            "statements": ["Text wandert ins Archiv."],
            "body": {"rules": [{"suffixes": [".md"], "target_root": 0}]},
        }
    )
    voyage = VoyageStore(base_dir=tmp_path, allowed_roots=roots).save(
        {
            "name": "Eigene Regeln",
            "steps": [
                {
                    "workflow": "cleanup_rules",
                    "job": {
                        "schema": "nemofold.job.v1",
                        "workflow": "cleanup_rules",
                        "input_roots": [str(documents)],
                        "target_roots": [str(archive)],
                        "output_dir": str(tmp_path / "out" / "01-cleanup"),
                        "privacy_mode": "local_only",
                        "action_mode": "dry_run",
                        "parameters": {
                            "allowed_extensions": [".txt"],
                            "rules": [{"suffixes": [".txt"], "target_root": 0}],
                        },
                    },
                }
            ],
        }
    )
    policy_store.bind(
        policy["policy_id"], target="voyage", voyage_id=voyage["voyage_id"]
    )

    result = run_voyage(
        voyage,
        ExecutionConfig(allowed_roots=roots),
        run_id="run_contract_wins",
        base_dir=tmp_path,
        policy_store=policy_store,
    )

    assert result.steps[0].policy_note == "Cleanup rules came from the job contract."
