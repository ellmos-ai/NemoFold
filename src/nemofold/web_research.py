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
from .contracts import ArtifactRecord, WorkflowBlocked
from .evidence import compute_coverage

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

WEB_WORKFLOWS = ("web_research", "dossier", "briefing")


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
    briefing_payload = build_briefing_payload(
        subject=subject,
        question=str(job.parameters.get("question", "")).strip() or (
            f"Dossier und Recherche zu: {subject}"
        ),
        meeting_context=str(job.parameters.get("meeting_context", "")).strip(),
        results=payload.get("results", []),
        allowed=payload.get("allowed", False),
        blocked_reasons=payload.get("blocked_reasons", []),
        min_sources=int(job.parameters.get("min_sources", 2)),
        sparse_sources_detected=bool(job.parameters.get("sparse_sources_detected", False)),
    )
    briefing_json = write_text_artifact(
        output / f"{run_id}.briefing.json",
        json.dumps(briefing_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "briefing",
    )
    briefing_md = write_text_artifact(
        output / f"{run_id}.briefing.md",
        render_briefing_markdown(briefing_payload),
        "briefing-markdown",
    )
    artifacts = (
        *artifacts,
        write_text_artifact(
            output / f"{run_id}.dossier.json",
            json.dumps(dossier, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "dossier",
        ),
        briefing_json,
        briefing_md,
    )
    metadata["dossier_subject"] = subject
    metadata["standing_note"] = dossier["standing_note"]
    metadata["briefing_status"] = briefing_payload["status"]
    metadata["is_limited"] = briefing_payload["is_limited"]
    return (*actions, f"assembled a dossier on {subject} from cited results"), artifacts, metadata


def build_briefing_payload(
    *,
    subject: str,
    question: str,
    meeting_context: str = "",
    results: list[dict[str, Any]] | tuple[WebResult, ...],
    allowed: bool,
    blocked_reasons: list[str] | tuple[str, ...],
    min_sources: int = 2,
    sparse_sources_detected: bool = False,
) -> dict[str, Any]:
    """Assemble a structured briefing separating facts, inferences, and open points."""
    source_count = len(results)
    is_limited = not allowed or (source_count < min_sources) or sparse_sources_detected
    limitation_reasons: list[str] = []
    if not allowed:
        status = "blocked_briefing"
        limitation_reasons = list(blocked_reasons)
    elif is_limited:
        status = "limited_briefing"
        if sparse_sources_detected and source_count >= min_sources:
            limitation_reasons.append(
                "Unzureichende Quellenlage: Datenlage als fragmentarisch eingestuft."
            )
        else:
            limitation_reasons.append(
                f"Unzureichende Quellenlage: Es wurden nur {source_count} Quelle(n) "
                f"gefunden (erforderlich: mindestens {min_sources})."
            )
    else:
        status = "complete_briefing"

    normalized_sources: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    for idx, item in enumerate(results, start=1):
        if isinstance(item, WebResult):
            query = item.query
            url = item.url
            title = item.title
            excerpt = item.excerpt
            rank = item.rank
        else:
            query = str(item.get("query", ""))
            url = str(item.get("url", ""))
            title = str(item.get("title", ""))
            excerpt = str(item.get("excerpt", ""))
            rank = int(item.get("rank", idx))
        normalized_sources.append(
            {
                "query": query,
                "url": url,
                "title": title,
                "excerpt": excerpt,
                "rank": rank,
                "anchor": f"{url} · rank {rank}",
            }
        )
        fact_id = f"F{idx:02d}"
        statement = f"Aus Quelle '{title}': {excerpt}" if excerpt else f"Quelle '{title}': {url}"
        facts.append(
            {
                "fact_id": fact_id,
                "statement": statement,
                "evidence_url": url,
                "evidence_excerpt": excerpt,
                "source_rank": rank,
            }
        )

    inferences: list[dict[str, Any]] = []
    if facts:
        inferences.append(
            {
                "inference_id": "I01",
                "statement": (
                    f"Auf Basis von {len(facts)} belegten Quellen liegt eine "
                    f"Informationsgrundlage für '{subject}' vor."
                ),
                "grounded_in_facts": [f["fact_id"] for f in facts],
                "confidence": "moderate" if is_limited else "high",
                "inference_note": "Schlussfolgerung, getrennt von belegten Fakten.",
            }
        )
        if meeting_context:
            inferences.append(
                {
                    "inference_id": "I02",
                    "statement": (
                        f"Relevanz für Termin '{meeting_context}': Belegte Aspekte ermöglichen "
                        "eine gezielte Vorbereitung, erfordern aber Nachfragen zu Lücken."
                    ),
                    "grounded_in_facts": [facts[0]["fact_id"]],
                    "confidence": "provisional" if is_limited else "high",
                    "inference_note": "Kontextuelle Schlussfolgerung für den Termin.",
                }
            )

    uncertainties: list[dict[str, Any]] = []
    if is_limited and allowed:
        uncertainties.append(
            {
                "point_id": "O01",
                "issue": "Unzureichende Quellendichte",
                "reason": (
                    f"Mit {source_count} Fundstelle(n) ist eine unabhängige "
                    "Kreuzvalidierung nicht gewährleistet."
                ),
                "recommended_action": (
                    "Vor dem Termin zusätzliche Primärquellen oder manuelle Klärung einholen."
                ),
            }
        )
    if allowed:
        uncertainties.append(
            {
                "point_id": f"O{len(uncertainties) + 1:02d}",
                "issue": "Aktualität öffentlich zugänglicher Webdaten",
                "reason": (
                    "Öffentliche Online-Quellen können zeitverzögert sein und kurzfristige "
                    "Änderungen unberücksichtigt lassen."
                ),
                "recommended_action": "Kernaussagen im direkten Termin rückbestätigen.",
            }
        )
        uncertainties.append(
            {
                "point_id": f"O{len(uncertainties) + 1:02d}",
                "issue": "Vertrauliche und interne Kontextfaktoren",
                "reason": "Nicht-öffentliche Vereinbarungen sind im Web nicht nachweisbar.",
                "recommended_action": "Spezifische Klärungsfragen auf die Agenda setzen.",
            }
        )
    else:
        uncertainties.append(
            {
                "point_id": "O01",
                "issue": "Web-Recherche blockiert",
                "reason": (
                    "Die Suche wurde durch Sicherheitsrichtlinien oder fehlende "
                    "Freigabe blockiert."
                ),
                "recommended_action": "Rechte und Adapterkonfiguration vor erneutem Lauf prüfen.",
            }
        )

    return {
        "schema": "nemofold.briefing.v1",
        "subject": subject,
        "question": question,
        "meeting_context": meeting_context,
        "status": status,
        "allowed": allowed,
        "blocked_reasons": list(blocked_reasons),
        "sources_evaluated": source_count,
        "sources": normalized_sources,
        "facts": facts,
        "inferences": inferences,
        "uncertainties_and_open_points": uncertainties,
        "is_limited": is_limited,
        "limitation_reasons": limitation_reasons,
        "separation_principle_note": (
            "Das Briefing trennt belegte Fakten strikt von Schlussfolgerungen "
            "und offenen Punkten."
        ),
        "source_sufficiency_note": (
            "Bei unzureichender Quellenlage wird ein begrenztes Briefing erstellt "
            "statt falscher Vollständigkeit."
        ),
    }


def render_briefing_markdown(payload: dict[str, Any]) -> str:
    """Render the briefing as human-readable Markdown with clear sections."""
    subject = payload["subject"]
    question = payload.get("question", "")
    meeting_context = payload.get("meeting_context", "")
    is_limited = payload.get("is_limited", False)

    lines = [
        f"# Briefing: {subject}",
        "",
        "## 1. Fragestellung und Kontext",
        "",
        f"- **Thema / Person:** {subject}",
        f"- **Fragestellung:** {question or 'Strukturierte Vorbereitung'}",
    ]
    if meeting_context:
        lines.append(f"- **Terminkontext:** {meeting_context}")
    lines.append(
        f"- **Status:** {'Begrenztes Briefing' if is_limited else 'Vollständiges Briefing'}"
    )
    lines.append("")

    if is_limited and payload.get("limitation_reasons"):
        lines.extend(
            [
                "> [!WARNING]",
                "> **Begrenztes Briefing:** Unzureichende Quellenlage. "
                "Falsche Vollständigkeit wird vermieden.",
            ]
        )
        for reason in payload["limitation_reasons"]:
            lines.append(f"> - {reason}")
        lines.append("")

    lines.extend(["## 2. Recherchequellen", ""])
    sources = payload.get("sources", [])
    if not sources:
        lines.append("Keine belegten Recherchequellen vorhanden.")
        lines.append("")
    else:
        for item in sources:
            lines.append(f"- **{item['title'] or item['url']}** (Rang {item['rank']})")
            lines.append(f"  - URL: {item['url']}")
            if item.get("excerpt"):
                lines.append(f"  > {item['excerpt']}")
        lines.append("")

    lines.extend(["## 3. Belegte Fakten (Synthese)", ""])
    facts = payload.get("facts", [])
    if not facts:
        lines.append("Keine belegten Fakten aus der Recherche extrahierbar.")
        lines.append("")
    else:
        for fact in facts:
            lines.append(
                f"- **[{fact['fact_id']}]** {fact['statement']} "
                f"(Beleg: {fact['evidence_url']})"
            )
        lines.append("")

    lines.extend(["## 4. Schlussfolgerungen", ""])
    inferences = payload.get("inferences", [])
    if not inferences:
        lines.append(
            "Aufgrund unzureichender Faktenlage wurden keine weiterführenden "
            "Schlussfolgerungen gezogen."
        )
        lines.append("")
    else:
        for inf in inferences:
            facts_str = ", ".join(inf.get("grounded_in_facts", []))
            lines.append(
                f"- **[{inf['inference_id']}]** {inf['statement']} "
                f"(Konfidenz: {inf['confidence']}, gestützt auf: {facts_str})"
            )
            if inf.get("inference_note"):
                lines.append(f"  *Hinweis:* {inf['inference_note']}")
        lines.append("")

    lines.extend(["## 5. Unsicherheiten und offene Punkte", ""])
    uncertainties = payload.get("uncertainties_and_open_points", [])
    if not uncertainties:
        lines.append("Keine offenen Unsicherheiten verzeichnet.")
        lines.append("")
    else:
        for point in uncertainties:
            lines.append(f"### Punkt {point['point_id']}: {point['issue']}")
            lines.append(f"- **Hintergrund:** {point['reason']}")
            lines.append(f"- **Empfohlene Maßnahme:** {point['recommended_action']}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def execute_briefing(
    job: Any,
    output_dir: str,
    run_id: str,
    *,
    server_allows: bool,
    approved: bool,
    adapter: WebSearchAdapter | None = None,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], dict[str, object]]:
    """Assemble a structured briefing from web research or verified previous output.

    Separates cited facts, clear inferences, and open uncertainties. If sources
    are sparse, creates a limited briefing instead of false completeness.
    """
    subject = str(job.parameters.get("subject", "")).strip()
    if not subject:
        raise ValueError("a briefing needs a declared subject")
    question = str(job.parameters.get("question", "")).strip() or (
        f"Recherche und strukturierte Vorbereitung zu: {subject}"
    )
    meeting_context = str(job.parameters.get("meeting_context", "")).strip()
    min_sources = int(job.parameters.get("min_sources", 2))
    sparse_sources_detected = bool(job.parameters.get("sparse_sources_detected", False))

    output = Path(output_dir)
    actions: list[str] = []
    artifacts: list[ArtifactRecord] = []

    # Check if a previous step already provided web research artifacts
    prior_payload: dict[str, Any] | None = None
    for root_str in getattr(job, "input_roots", ()):
        root_path = Path(root_str)
        if root_path.is_dir():
            for cand in sorted(root_path.glob("*.web-research.json")):
                try:
                    prior_payload = json.loads(cand.read_text(encoding="utf-8"))
                    break
                except (OSError, ValueError):
                    pass
        elif root_path.is_file() and root_path.name.endswith(".web-research.json"):
            try:
                prior_payload = json.loads(root_path.read_text(encoding="utf-8"))
                break
            except (OSError, ValueError):
                pass
        if prior_payload is not None:
            break

    if prior_payload is not None:
        web_payload = prior_payload
        actions.append("reused verified web research from previous voyage step")
    else:
        # Carry out or evaluate search
        sub_actions, sub_artifacts, _ = execute_web_research(
            job,
            output_dir,
            run_id,
            server_allows=server_allows,
            approved=approved,
            adapter=adapter,
        )
        actions.extend(sub_actions)
        artifacts.extend(sub_artifacts)
        payload_path = output / f"{run_id}.web-research.json"
        web_payload = json.loads(payload_path.read_text(encoding="utf-8"))

    allowed = bool(web_payload.get("allowed", False))
    blocked_reasons = tuple(web_payload.get("blocked_reasons", []))
    results = web_payload.get("results", [])

    briefing_payload = build_briefing_payload(
        subject=subject,
        question=question,
        meeting_context=meeting_context,
        results=results,
        allowed=allowed,
        blocked_reasons=blocked_reasons,
        min_sources=min_sources,
        sparse_sources_detected=sparse_sources_detected,
    )

    briefing_json = write_text_artifact(
        output / f"{run_id}.briefing.json",
        json.dumps(briefing_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "briefing",
    )
    briefing_md = write_text_artifact(
        output / f"{run_id}.briefing.md",
        render_briefing_markdown(briefing_payload),
        "briefing-markdown",
    )
    artifacts.extend([briefing_json, briefing_md])

    metadata: dict[str, object] = {
        "briefing_subject": subject,
        "briefing_status": briefing_payload["status"],
        "is_limited": briefing_payload["is_limited"],
        "sources_evaluated": briefing_payload["sources_evaluated"],
        "facts_count": len(briefing_payload["facts"]),
        "inferences_count": len(briefing_payload["inferences"]),
        "open_points_count": len(briefing_payload["uncertainties_and_open_points"]),
        "separation_principle_note": briefing_payload["separation_principle_note"],
    }
    if not allowed:
        metadata["blocked"] = True
        metadata["blocked_reasons"] = list(blocked_reasons)
        actions.append("briefing generation blocked due to web search restrictions")
        raise WorkflowBlocked(
            blocked_reasons or ("web_search_restrictions",),
            actions=tuple(actions),
            artifacts=tuple(artifacts),
            coverage=compute_coverage(
                all_source_ids=(), read_source_ids={}, cited_source_ids=set()
            ),
            metadata=metadata,
        )

    if (
        job.parameters.get("require_sufficient_sources", False) is True
        and briefing_payload["is_limited"]
    ):
        metadata["needs_user_input"] = True
        actions.append("briefing blocked: require_sufficient_sources unsatisfied")
        raise WorkflowBlocked(
            ("insufficient_sources_for_briefing",),
            actions=tuple(actions),
            artifacts=tuple(artifacts),
            coverage=compute_coverage(
                all_source_ids=(), read_source_ids={}, cited_source_ids=set()
            ),
            metadata=metadata,
        )

    if briefing_payload["is_limited"]:
        actions.append(
            f"assembled limited briefing on {subject} ({len(results)} source(s))"
        )
    else:
        actions.append(
            f"assembled complete briefing on {subject} ({len(results)} source(s))"
        )

    return tuple(actions), tuple(artifacts), metadata


