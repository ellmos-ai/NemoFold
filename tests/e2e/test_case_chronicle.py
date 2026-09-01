from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.job_io import parse_job_payload

CASE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "synthetic-case"
PLACES = ["Uferstraße", "Kiosk", "Werkstatt", "Betriebshof", "zu Hause", "Revier Nord"]


@pytest.fixture
def case(tmp_path: Path) -> Path:
    documents = tmp_path / "akte"
    shutil.copytree(CASE_ROOT, documents)
    return documents


def _run(tmp_path: Path, documents: Path, workflow: str, run_id: str, **parameters):
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": workflow,
            "input_roots": [str(documents)],
            "output_dir": str(tmp_path / "out" / workflow),
            "questions": list(parameters.pop("questions", [])),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": parameters,
        },
        base_dir=tmp_path,
    )
    return run_job(job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id=run_id)


def _ledger_artifacts(result) -> dict[str, str]:
    ledger = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
    return {
        Path(item["path"]).name: item["sha256"]
        for item in ledger["artifacts"]
        if item.get("sha256")
    }


def _verify_hashes(result) -> None:
    """Every recorded hash must match the bytes actually on disk."""
    ledger = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
    checked = 0
    for item in ledger["artifacts"]:
        digest = item.get("sha256")
        if not digest:
            continue
        data = Path(item["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, item["path"]
        checked += 1
    assert checked >= 2


# --------------------------------------------------------------------------- #
# K5
# --------------------------------------------------------------------------- #


def test_person_registry_writes_an_identified_and_a_pseudonymous_form(tmp_path, case) -> None:
    result = _run(tmp_path, case, "person_registry", "case_registry", formats=["md"])

    assert result.report.status is RunStatus.EXECUTED
    names = _ledger_artifacts(result)
    assert "case_registry.person-registry.json" in names
    assert "case_registry.person-registry.pseudonymous.json" in names
    assert "case_registry.identity-map.json" in names
    _verify_hashes(result)

    output = Path(tmp_path / "out" / "person_registry")
    public = (output / "case_registry.person-registry.pseudonymous.json").read_text(
        encoding="utf-8"
    )
    identity = json.loads((output / "case_registry.identity-map.json").read_text(encoding="utf-8"))
    # The form meant to travel carries no real name; the map that carries them
    # is a separate file and says it must stay behind.
    for name in identity["map"].values():
        assert name not in public
    assert "must not travel" in identity["note"]
    assert result.report.metadata["person_count"] == 7


# --------------------------------------------------------------------------- #
# K5 relations
# --------------------------------------------------------------------------- #


def test_relation_model_draws_only_edges_a_sentence_states(tmp_path, case) -> None:
    result = _run(tmp_path, case, "relation_model", "case_relations", formats=["md"])

    assert result.report.status is RunStatus.EXECUTED
    output = Path(tmp_path / "out" / "relation_model")
    payload = json.loads((output / "case_relations.relations.json").read_text(encoding="utf-8"))
    assert payload["relation_count"] >= 1
    assert all(edge.get("quote") for edge in payload["relations"])
    svg = (output / "case_relations.relations.svg").read_text(encoding="utf-8")
    assert svg.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert 'role="img"' in svg and "<desc>" in svg
    # The legend names both kinds in words, not only by stroke.
    assert "stated relation" in svg and "named together" in svg
    _verify_hashes(result)


def test_the_relation_graph_renders_to_identical_bytes_twice(tmp_path, case) -> None:
    _run(tmp_path, case, "relation_model", "case_rel_a", formats=["md"])
    _run(tmp_path, case, "relation_model", "case_rel_b", formats=["md"])

    output = Path(tmp_path / "out" / "relation_model")
    left = (output / "case_rel_a.relations.svg").read_bytes()
    right = (output / "case_rel_b.relations.svg").read_bytes()
    assert hashlib.sha256(left).hexdigest() == hashlib.sha256(right).hexdigest()


# --------------------------------------------------------------------------- #
# K4
# --------------------------------------------------------------------------- #


def test_person_timeline_keeps_an_unstated_time_undetermined(tmp_path, case) -> None:
    result = _run(tmp_path, case, "person_timeline", "case_timeline", formats=["md"])

    assert result.report.status is RunStatus.EXECUTED
    output = Path(tmp_path / "out" / "person_timeline")
    payload = json.loads((output / "case_timeline.timeline.json").read_text(encoding="utf-8"))
    assert payload["undetermined_count"] >= 1
    undetermined = [event for event in payload["events"] if not event["determined"]]
    assert all(event["start"] is None for event in undetermined)
    assert "never placed at a guessed moment" in payload["honesty_note"]
    svg = (output / "case_timeline.timeline.svg").read_text(encoding="utf-8")
    assert "unbestimmt" in svg
    assert "undetermined" in svg
    _verify_hashes(result)


def test_coverage_timeline_reads_the_declared_contract_intervals(tmp_path, case) -> None:
    result = _run(tmp_path, case, "coverage_timeline", "case_coverage", formats=["md"])

    assert result.report.status is RunStatus.EXECUTED
    output = Path(tmp_path / "out" / "coverage_timeline")
    payload = json.loads((output / "case_coverage.timeline.json").read_text(encoding="utf-8"))
    labels = {event["label"]: (event["start"], event["end"]) for event in payload["events"]}
    assert labels["Teilkasko"] == ("2026-01-01", "2026-12-31")
    assert labels["Vollkasko"] == ("2026-03-01", "2026-12-31")
    assert "open end" in result.report.metadata["open_end_note"]
    _verify_hashes(result)


# --------------------------------------------------------------------------- #
# K6
# --------------------------------------------------------------------------- #


def test_alibi_weave_separates_one_line_from_two_and_shows_the_gaps(tmp_path, case) -> None:
    result = _run(
        tmp_path,
        case,
        "alibi_weave",
        "case_weave",
        formats=["md"],
        places=PLACES,
        window="14.-15.03.2026",
    )

    assert result.report.status is RunStatus.EXECUTED
    output = Path(tmp_path / "out" / "alibi_weave")
    payload = json.loads((output / "case_weave.alibi-weave.json").read_text(encoding="utf-8"))
    assert payload["corroborated_count"] == 1
    assert payload["gap_count"] >= 1
    confirmed = next(
        item for item in payload["positions"] if item["support"] == "fremdbestaetigt"
    )
    # Both sentences are in the artifact, so the inference can be judged.
    assert confirmed["confirmations"][0]["naming_quote"]
    assert confirmed["confirmations"][0]["context_quote"]
    assert "not proof of anything" in payload["reasoning_note"]
    svg = (output / "case_weave.alibi-weave.svg").read_text(encoding="utf-8")
    assert "selbstauskunft" in svg and "fremdbestaetigt" in svg
    assert "Lücke" in svg and "url(#nf-gap)" in svg
    _verify_hashes(result)


def test_contradiction_synopsis_keeps_both_wordings(tmp_path, case) -> None:
    result = _run(
        tmp_path,
        case,
        "contradiction_synopsis",
        "case_contra",
        formats=["md"],
        contested_terms=["Golf"],
    )

    assert result.report.status is RunStatus.EXECUTED
    output = Path(tmp_path / "out" / "contradiction_synopsis")
    payload = json.loads((output / "case_contra.contradictions.json").read_text(encoding="utf-8"))
    assert payload["contested_term_count"] == 1
    readings = payload["contested_terms"][0]["readings"]
    sources = {item["source_id"] for item in readings}
    assert len(sources) >= 2
    assert "does not decide which of them is right" in payload["synopsis_rule"]
    _verify_hashes(result)


# --------------------------------------------------------------------------- #
# K7
# --------------------------------------------------------------------------- #


def test_corpus_query_answers_the_blue_golf_question_in_quotes(tmp_path, case) -> None:
    result = _run(
        tmp_path,
        case,
        "corpus_query",
        "case_query",
        formats=["md"],
        terms=["blauer VW Golf", "blaue"],
        partition_size=6,
    )

    assert result.report.status is RunStatus.EXECUTED
    output = Path(tmp_path / "out" / "corpus_query")
    payload = json.loads((output / "case_query.corpus-query.json").read_text(encoding="utf-8"))
    assert payload["match_count"] >= 1
    assert payload["partition_count"] >= 1
    assert [stage["name"] for stage in payload["stages"]] == [
        "partition",
        "fold-partition",
        "fold-final",
    ]
    # Every answer is a sentence from a source, with the anchors that carry it.
    for match in payload["matches"]:
        assert match["anchors"]
        assert all(anchor["line"] > 0 for anchor in match["anchors"])
    assert any("Golf" in match["statement"] for match in payload["matches"])
    assert "no match means the corpus does not contain one" in payload["quote_rule"]
    _verify_hashes(result)


def test_a_question_the_corpus_cannot_answer_is_an_honest_empty_report(tmp_path, case) -> None:
    result = _run(
        tmp_path,
        case,
        "corpus_query",
        "case_query_empty",
        formats=["md"],
        terms=["Hubschrauber"],
    )

    assert result.report.status is RunStatus.EXECUTED
    output = Path(tmp_path / "out" / "corpus_query")
    payload = json.loads(
        (output / "case_query_empty.corpus-query.json").read_text(encoding="utf-8")
    )
    assert payload["match_count"] == 0
    findings = (output / "case_query_empty_query.md").read_text(encoding="utf-8")
    assert "That is the finding, not a missing file." in findings


# --------------------------------------------------------------------------- #
# The chronicle draws no legal conclusion, and says so everywhere
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("workflow", "parameters"),
    [
        ("person_registry", {}),
        ("relation_model", {}),
        ("person_timeline", {}),
        ("coverage_timeline", {}),
        ("alibi_weave", {"places": PLACES}),
        ("contradiction_synopsis", {"contested_terms": ["Golf"]}),
        ("corpus_query", {"terms": ["Golf"]}),
    ],
)
def test_every_chronicle_workflow_refuses_to_conclude(tmp_path, case, workflow, parameters):
    result = _run(tmp_path, case, workflow, f"case_{workflow}", formats=["md"], **parameters)

    assert result.report.status is RunStatus.EXECUTED
    assert "draws no legal conclusion" in result.report.metadata["no_legal_conclusion"]
    assert result.report.metadata.get("cloud_proof", False) is False
