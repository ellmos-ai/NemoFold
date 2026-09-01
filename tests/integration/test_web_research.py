from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from nemofold.application import (
    ExecutionConfig,
    authorize_web_search,
    release_web_search,
    run_job,
)
from nemofold.contracts import RunStatus
from nemofold.job_io import parse_job_payload
from nemofold.web_research import (
    TAVILY_KEY_ENV,
    WebResult,
    evaluate_web_search,
    parse_tavily,
    validate_queries,
)


@dataclass(frozen=True, slots=True)
class FakeSearch:
    """A local stand-in. No test in this suite ever reaches the network."""

    name: str = "tavily"

    def readiness(self) -> tuple[bool, str]:
        return True, ""

    def search(self, queries: tuple[str, ...], *, max_results: int) -> tuple[WebResult, ...]:
        return tuple(
            WebResult(
                query=query,
                url=f"https://example.invalid/{index}",
                title=f"Beispielquelle {index}",
                excerpt=f"Auszug zu {query}.",
                rank=index,
            )
            for query in queries
            for index in range(1, min(max_results, 2) + 1)
        )


def _job(tmp_path: Path, workflow: str, **parameters):
    return parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": workflow,
            "input_roots": [str(tmp_path / "leer")],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": parameters,
        },
        base_dir=tmp_path,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "leer").mkdir()
    (tmp_path / "leer" / "hinweis.txt").write_text("kein Inhalt", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# The gate collects every reason, not the first
# --------------------------------------------------------------------------- #


def test_a_search_needs_all_four_conditions_together() -> None:
    decision = evaluate_web_search(
        adapter="tavily",
        queries=("wetter morgen",),
        refused=(),
        server_allows=False,
        approved=False,
        max_results=5,
        adapter_ready=False,
        adapter_reason=f"web_search_key_missing:{TAVILY_KEY_ENV}",
    )

    assert decision.allowed is False
    assert "web_search_disabled_on_this_server" in decision.reasons
    assert "web_search_not_approved_for_this_call" in decision.reasons
    assert f"web_search_key_missing:{TAVILY_KEY_ENV}" in decision.reasons
    # All of them, so one fix does not look like the only thing missing.
    assert len(decision.reasons) == 3


def test_all_four_conditions_together_allow_it() -> None:
    decision = evaluate_web_search(
        adapter="tavily",
        queries=("wetter morgen",),
        refused=(),
        server_allows=True,
        approved=True,
        max_results=5,
        adapter_ready=True,
    )

    assert decision.allowed is True
    assert decision.reasons == ()


@pytest.mark.parametrize(
    "query",
    [
        "was kostet ines@example.invalid",
        "recherche zu C:\\Users\\lukas\\akte",
        "wer hat die nummer +49 30 1234567",
    ],
)
def test_a_query_carrying_private_content_is_refused_not_rewritten(query) -> None:
    queries, refused = validate_queries([query, "unverfängliche frage"])

    # Refusal, not redaction: a silently rewritten query is a query the person
    # never asked, and they would read the answer as if they had.
    assert queries == ("unverfängliche frage",)
    assert refused and "pseudonymization preflight" in refused[0]


def test_a_refused_query_blocks_the_run_it_belongs_to() -> None:
    queries, refused = validate_queries(["schreib an ines@example.invalid"])
    decision = evaluate_web_search(
        adapter="tavily",
        queries=queries,
        refused=refused,
        server_allows=True,
        approved=True,
        max_results=5,
        adapter_ready=True,
    )

    assert decision.allowed is False
    assert any("preflight" in reason for reason in decision.reasons)


def test_a_hit_without_an_address_is_not_a_hit() -> None:
    body = {
        "results": [
            {"url": "https://example.invalid/a", "title": "A", "content": "x"},
            {"title": "no url at all", "content": "y"},
            {"url": "javascript:alert(1)", "title": "B", "content": "z"},
        ]
    }

    results = parse_tavily("frage", body, 5)

    assert [item.url for item in results] == ["https://example.invalid/a"]


# --------------------------------------------------------------------------- #
# The workflows
# --------------------------------------------------------------------------- #


def test_without_permission_the_run_blocks_honestly_and_sends_nothing(workspace) -> None:
    job = _job(workspace, "web_research", queries=["wie funktioniert eine police"])

    result = run_job(job, ExecutionConfig(allowed_roots=(str(workspace),)), run_id="web_blocked")

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["blocked"] is True
    assert result.report.metadata["web_transfer_performed"] is False
    payload = json.loads(
        (workspace / "out" / "web_blocked.web-research.json").read_text(encoding="utf-8")
    )
    assert payload["allowed"] is False
    assert payload["results"] == []
    note = (workspace / "out" / "web_blocked_Web research.md").read_text(encoding="utf-8")
    assert "Nothing was sent anywhere." in note


def test_an_approved_search_keeps_every_result_with_its_address(workspace) -> None:
    job = _job(workspace, "web_research", queries=["police laufzeit"], max_results=2)
    authorize_web_search(
        "web_ok", server_allows=True, approved=True, adapter=FakeSearch()
    )
    try:
        result = run_job(
            job,
            ExecutionConfig(allowed_roots=(str(workspace),), web_search_allowed=True),
            run_id="web_ok",
        )
    finally:
        release_web_search("web_ok")

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["web_transfer_performed"] is True
    payload = json.loads(
        (workspace / "out" / "web_ok.web-research.json").read_text(encoding="utf-8")
    )
    assert payload["result_count"] == 2
    assert all(item["url"].startswith("https://") for item in payload["results"])
    notes = (workspace / "out" / "web_ok_web-notes.md").read_text(encoding="utf-8")
    assert "https://example.invalid/1" in notes
    assert "Nothing here was written by this program." in notes
    # The key is never written into anything the run leaves behind.
    assert TAVILY_KEY_ENV in payload["key_note"]
    assert "never stored" in payload["key_note"]


def test_a_stored_job_cannot_carry_its_own_approval(workspace) -> None:
    # The same job, run without an authorizing caller, must block again.
    job = _job(workspace, "web_research", queries=["police laufzeit"])
    authorize_web_search("first", server_allows=True, approved=True, adapter=FakeSearch())
    try:
        run_job(
            job,
            ExecutionConfig(allowed_roots=(str(workspace),), web_search_allowed=True),
            run_id="first",
        )
    finally:
        release_web_search("first")

    again = run_job(job, ExecutionConfig(allowed_roots=(str(workspace),)), run_id="second")

    assert again.report.metadata["blocked"] is True
    assert "web_search_not_approved_for_this_call" in (
        again.report.metadata["web_search_blocked_reasons"]
    )


def test_a_dossier_says_it_is_a_reading_list_and_not_a_finding(workspace) -> None:
    job = _job(
        workspace,
        "dossier",
        subject="Hilde Vandermolen",
        queries=["Hilde Vandermolen Publikationen"],
        max_results=2,
    )
    authorize_web_search("dossier_ok", server_allows=True, approved=True, adapter=FakeSearch())
    try:
        result = run_job(
            job,
            ExecutionConfig(allowed_roots=(str(workspace),), web_search_allowed=True),
            run_id="dossier_ok",
        )
    finally:
        release_web_search("dossier_ok")

    assert result.report.status is RunStatus.EXECUTED
    dossier = json.loads(
        (workspace / "out" / "dossier_ok.dossier.json").read_text(encoding="utf-8")
    )
    # The subject is fictional, and the artifact refuses to be read as a verdict.
    assert dossier["subject"] == "Hilde Vandermolen"
    assert dossier["entries"]
    assert "not a finding about the subject" in dossier["standing_note"]
    assert "a search result is not evidence that something is true" in dossier["standing_note"]


def test_a_dossier_without_a_subject_is_refused(workspace) -> None:
    job = _job(workspace, "dossier", queries=["irgendwas"])

    result = run_job(job, ExecutionConfig(allowed_roots=(str(workspace),)), run_id="no_subject")

    assert result.report.status is RunStatus.FAILED
