"""K3: the outside world, behind the same kind of gate as a model.

Searching the web is the first thing in this product that sends words to a
stranger, so it is gated like the model adapters and not like a feature. Four
conditions have to hold together, and a run that misses any of them ends
blocked with the reasons named rather than degrading into something quieter:

* the server was started with web search allowed;
* the caller approved this specific call;
* an API key exists in the environment - never in a job, a draft or a store;
* the queries survive a pseudonymization preflight.

That last one is the point most easily lost. A query is the one place where
content from an approved root leaves the host as *text a person wrote*, so a
query carrying an email address, a path or a phone number is refused before any
adapter sees it. Approving a search is not approving the export of a folder.

Every result carries its URL, its title and the excerpt that was actually
returned. A claim from the web is only ever as good as the line it quotes, and
here that line has an address.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .anonymizer import detect_sensitive_categories
from .artifacts import write_text_artifact
from .contracts import ArtifactRecord

WEB_ADAPTERS = ("tavily",)
TAVILY_KEY_ENV = "TAVILY_API_KEY"
TAVILY_ENDPOINT = "https://api.tavily.com/search"

MAX_QUERIES = 8
MAX_QUERY_CHARS = 300
MAX_RESULTS_PER_QUERY = 10
MAX_EXCERPT_CHARS = 600
DEFAULT_TIMEOUT_SECONDS = 30.0


class WebSearchError(RuntimeError):
    """Raised when a permitted search could not be carried out."""


@dataclass(frozen=True, slots=True)
class WebResult:
    """One returned hit, with the address that makes it checkable."""

    query: str
    url: str
    title: str
    excerpt: str
    rank: int

    @property
    def anchor(self) -> str:
        return f"{self.url} · rank {self.rank}"


@dataclass(frozen=True, slots=True)
class WebSearchDecision:
    """Whether this search may happen, and every reason it may not."""

    allowed: bool
    reasons: tuple[str, ...]
    adapter: str
    queries: tuple[str, ...]
    max_results: int

    def as_metadata(self) -> dict[str, object]:
        return {
            "web_adapter": self.adapter,
            "web_search_allowed": self.allowed,
            "web_search_blocked_reasons": list(self.reasons),
            "web_query_count": len(self.queries),
            "web_transfer_performed": False,
        }


class WebSearchAdapter(Protocol):
    """The whole surface an outside search has.

    ``readiness`` is separate from ``search`` on purpose. Whether a credential
    exists is a fact about this adapter, not about the gate, so the gate asks
    rather than assuming that every adapter is a keyed HTTP service.
    """

    @property
    def name(self) -> str: ...

    def readiness(self) -> tuple[bool, str]: ...

    def search(
        self, queries: tuple[str, ...], *, max_results: int
    ) -> tuple[WebResult, ...]: ...


def validate_queries(raw: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Check the queries and refuse any that would carry private content out.

    Refusal, not redaction. A query silently rewritten is a query the person did
    not ask, and they would never learn that the search they read was a
    different one.
    """
    if not isinstance(raw, list) or not raw:
        raise ValueError("web search needs a non-empty list of queries")
    if len(raw) > MAX_QUERIES:
        raise ValueError(f"web search accepts at most {MAX_QUERIES} queries")
    queries: list[str] = []
    refused: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("every query must be a string")
        text = " ".join(item.split())
        if not text:
            continue
        if len(text) > MAX_QUERY_CHARS:
            raise ValueError(f"a query may not exceed {MAX_QUERY_CHARS} characters")
        categories = detect_sensitive_categories(text)
        if categories:
            refused.append(
                f"query refused by the pseudonymization preflight, it carries "
                f"{', '.join(categories)}: {text[:60]}"
            )
            continue
        queries.append(text)
    if not queries and not refused:
        raise ValueError("web search needs at least one non-empty query")
    return tuple(queries), tuple(refused)


def evaluate_web_search(
    *,
    adapter: str,
    queries: tuple[str, ...],
    refused: tuple[str, ...],
    server_allows: bool,
    approved: bool,
    max_results: int,
    adapter_ready: bool,
    adapter_reason: str = "",
) -> WebSearchDecision:
    """Collect every reason this search may not happen, not just the first."""
    reasons: list[str] = []
    if adapter not in WEB_ADAPTERS:
        reasons.append(f"web_adapter_unknown:{adapter}")
    if not server_allows:
        reasons.append("web_search_disabled_on_this_server")
    if not approved:
        reasons.append("web_search_not_approved_for_this_call")
    if not adapter_ready:
        reasons.append(adapter_reason or "web_adapter_not_ready")
    if not 1 <= max_results <= MAX_RESULTS_PER_QUERY:
        reasons.append(f"web_result_ceiling_invalid:{max_results}")
    reasons.extend(refused)
    if not queries:
        reasons.append("web_search_has_no_usable_query")
    return WebSearchDecision(
        allowed=not reasons,
        reasons=tuple(reasons),
        adapter=adapter,
        queries=queries,
        max_results=max_results,
    )


@dataclass(frozen=True, slots=True)
class TavilyAdapter:
    """Tavily search. The key is read from the environment at call time only.

    It is never taken from a job, written into a draft, stored in the library or
    put in a report: a key that can be saved is a key that will be shared.
    """

    name: str = "tavily"
    endpoint: str = TAVILY_ENDPOINT
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def readiness(self) -> tuple[bool, str]:
        if os.environ.get(TAVILY_KEY_ENV, "").strip():
            return True, ""
        return False, f"web_search_key_missing:{TAVILY_KEY_ENV}"

    def search(
        self, queries: tuple[str, ...], *, max_results: int
    ) -> tuple[WebResult, ...]:
        key = os.environ.get(TAVILY_KEY_ENV, "").strip()
        if not key:
            raise WebSearchError(f"{TAVILY_KEY_ENV} is not set")
        results: list[WebResult] = []
        for query in queries:
            payload = json.dumps(
                {"api_key": key, "query": query, "max_results": max_results}
            ).encode("utf-8")
            request = urllib.request.Request(  # noqa: S310 - fixed https endpoint
                self.endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(  # noqa: S310 - fixed https endpoint
                    request, timeout=self.timeout_seconds
                ) as reply:
                    body = json.loads(reply.read().decode("utf-8"))
            except (OSError, urllib.error.URLError, ValueError) as exc:
                raise WebSearchError(f"tavily search failed: {exc}") from exc
            results.extend(parse_tavily(query, body, max_results))
        return tuple(results)


def parse_tavily(query: str, body: Any, max_results: int) -> tuple[WebResult, ...]:
    """Read a Tavily response into results, keeping only what is citable."""
    if not isinstance(body, dict):
        raise WebSearchError("tavily returned an unexpected payload")
    raw = body.get("results")
    if not isinstance(raw, list):
        raise WebSearchError("tavily returned no result list")
    found: list[WebResult] = []
    for rank, item in enumerate(raw[:max_results], start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            # A hit without an address cannot be checked, so it is not a hit.
            continue
        found.append(
            WebResult(
                query=query,
                url=url,
                title=" ".join(str(item.get("title", "")).split())[:200],
                excerpt=" ".join(str(item.get("content", "")).split())[:MAX_EXCERPT_CHARS],
                rank=rank,
            )
        )
    return tuple(found)


def research_payload(
    decision: WebSearchDecision, results: tuple[WebResult, ...]
) -> dict[str, object]:
    return {
        "schema": "nemofold.web-research.v1",
        "adapter": decision.adapter,
        "allowed": decision.allowed,
        "blocked_reasons": list(decision.reasons),
        "queries": list(decision.queries),
        "result_count": len(results),
        "results": [
            {
                "query": item.query,
                "url": item.url,
                "title": item.title,
                "excerpt": item.excerpt,
                "rank": item.rank,
            }
            for item in results
        ],
        "key_note": (
            f"The API key is read from {TAVILY_KEY_ENV} at call time and is never "
            "stored in a job, a draft, the library or this report."
        ),
        "citation_note": (
            "Every line here came back from a search with the address it came from. "
            "Nothing was summarised into a claim without one."
        ),
    }


# --------------------------------------------------------------------------- #
# The two workflows, as thin contracts over the gate
# --------------------------------------------------------------------------- #

WEB_WORKFLOWS = ("web_research", "dossier")


def default_adapter(name: str) -> WebSearchAdapter:
    """The adapter a run uses. Tests replace this; nothing else should."""
    if name == "tavily":
        return TavilyAdapter()
    raise WebSearchError(f"unknown web adapter: {name}")


def _blocked(decision: WebSearchDecision, output: Path, run_id: str, title: str):
    """Write the honest refusal. A blocked search still leaves a record."""
    payload = research_payload(decision, ())
    artifact = write_text_artifact(
        output / f"{run_id}.web-research.json",
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "web-research-blocked",
    )
    note = write_text_artifact(
        output / f"{run_id}_{title}.md",
        f"# {title}\n\nNo search was carried out. Every reason:\n\n"
        + "".join(f"- {reason}\n" for reason in decision.reasons)
        + "\nNothing was sent anywhere.\n",
        "findings-blocked",
    )
    return artifact, note, payload


def execute_web_research(
    job: Any,
    output_dir: str,
    run_id: str,
    *,
    server_allows: bool,
    approved: bool,
    adapter: WebSearchAdapter | None = None,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], dict[str, object]]:
    """Search, and return only what came back with an address."""
    name = str(job.parameters.get("web_adapter", "tavily"))
    max_results = int(job.parameters.get("max_results", 5))
    raw = job.parameters.get("queries") or list(job.questions)
    queries, refused = validate_queries(raw)
    try:
        worker = adapter or default_adapter(name)
        ready, reason = worker.readiness()
    except WebSearchError as exc:
        worker, ready, reason = None, False, f"web_adapter_unknown:{exc}"
    decision = evaluate_web_search(
        adapter=name,
        queries=queries,
        refused=refused,
        server_allows=server_allows,
        approved=approved,
        max_results=max_results,
        adapter_ready=ready,
        adapter_reason=reason,
    )
    output = Path(output_dir)
    if not decision.allowed:
        artifact, note, payload = _blocked(decision, output, run_id, "Web research")
        metadata = decision.as_metadata()
        metadata["blocked"] = True
        metadata["key_note"] = payload["key_note"]
        return (
            ("no search was carried out; every blocking reason is in the report",),
            (artifact, note),
            metadata,
        )
    assert worker is not None
    results = worker.search(decision.queries, max_results=decision.max_results)
    payload = research_payload(decision, results)
    artifacts = [
        write_text_artifact(
            output / f"{run_id}.web-research.json",
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "web-research",
        ),
        write_text_artifact(
            output / f"{run_id}_web-notes.md",
            _notes_markdown(decision, results),
            "web-notes",
        ),
    ]
    metadata = decision.as_metadata()
    metadata["web_transfer_performed"] = True
    metadata["result_count"] = len(results)
    metadata["citation_note"] = payload["citation_note"]
    return (
        (
            f"searched {len(decision.queries)} query(ies) through {name} and kept "
            f"{len(results)} result(s), each with its address",
        ),
        tuple(artifacts),
        metadata,
    )


def _notes_markdown(decision: WebSearchDecision, results: tuple[WebResult, ...]) -> str:
    lines = ["# Web research notes", ""]
    lines.append(
        "Every line below came back from a search and carries the address it came "
        "from. Nothing here was written by this program.\n"
    )
    for query in decision.queries:
        lines.append(f"## {query}")
        lines.append("")
        hits = [item for item in results if item.query == query]
        if not hits:
            lines.append("Nothing came back for this query.")
            lines.append("")
            continue
        for item in hits:
            lines.append(f"- **{item.title or item.url}** — {item.url}")
            if item.excerpt:
                lines.append(f"  > {item.excerpt}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def execute_dossier(
    job: Any,
    output_dir: str,
    run_id: str,
    *,
    server_allows: bool,
    approved: bool,
    adapter: WebSearchAdapter | None = None,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], dict[str, object]]:
    """Assemble a dossier on a declared subject out of cited search results.

    The subject is whatever a person typed. This workflow makes no judgement
    about them, states only what a source said with its address, and says in the
    artifact that it is a reading list rather than a finding.
    """
    subject = str(job.parameters.get("subject", "")).strip()
    if not subject:
        raise ValueError("a dossier needs a declared subject")
    actions, artifacts, metadata = execute_web_research(
        job,
        output_dir,
        run_id,
        server_allows=server_allows,
        approved=approved,
        adapter=adapter,
    )
    output = Path(output_dir)
    payload_path = output / f"{run_id}.web-research.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    dossier = {
        "schema": "nemofold.dossier.v1",
        "subject": subject,
        "assembled_from": payload["result_count"],
        "allowed": payload["allowed"],
        "blocked_reasons": payload["blocked_reasons"],
        "entries": payload["results"],
        "standing_note": (
            "This dossier is a reading list with addresses, not a finding about the "
            "subject. Nothing here was verified, weighed or concluded, and a search "
            "result is not evidence that something is true."
        ),
    }
    artifacts = (
        *artifacts,
        write_text_artifact(
            output / f"{run_id}.dossier.json",
            json.dumps(dossier, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "dossier",
        ),
    )
    metadata["dossier_subject"] = subject
    metadata["standing_note"] = dossier["standing_note"]
    return (*actions, f"assembled a dossier on {subject} from cited results"), artifacts, metadata
