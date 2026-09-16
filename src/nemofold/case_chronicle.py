"""Case Chronicle workflows: thin contracts over the four deep-analysis cores.

Each function here is the workflow half of one core - it reads declared
parameters, calls into entity_relation, timeline, corroboration or the staged
aggregation, and turns the result into artifacts, claims and coverage. The
reasoning lives in the cores; what lives here is the contract.

Nothing in this module draws a legal conclusion, and the reports say so. What
they produce is what the documents state, who states it, and where they are
silent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import write_text_artifact
from .chronicle_svg import alibi_weave_svg, relation_graph_svg, timeline_svg
from .completeness import Question, needs_input_payload
from .contracts import ArtifactRecord, Claim, Coverage, EvidenceLocator, WorkflowBlocked
from .corroboration import _minutes, suggest_places, weave_alibis, weave_payload
from .entity_relation import build_entity_graph, registry_payload
from .evidence import compute_coverage
from .primitives import AggregationBudget, AnchoredStatement, aggregate_mapreduce, merge_sections
from .primitives import statements_from_texts as _statements
from .report_studio import ReportDocument, render_report_formats
from .timeline import (
    cost_timeline_payload,
    extract_costs,
    extract_coverage,
    extract_events,
    timeline_payload,
)

CHRONICLE_WORKFLOWS = (
    "person_registry",
    "relation_model",
    "person_timeline",
    "coverage_timeline",
    "cost_timeline",
    "subscription_reconcile",
    "medication_reconcile",
    "alibi_weave",
    "contradiction_synopsis",
    "corpus_query",
)

NO_LEGAL_CONCLUSION = (
    "This report states what the approved sources say and where they are silent. "
    "It draws no legal conclusion and establishes no fact."
)


@dataclass(frozen=True, slots=True)
class ChronicleInput:
    """What every chronicle workflow needs: ordered sources and their text."""

    source_ids: tuple[str, ...]
    texts: dict[str, str]


def _tuple_param(job: Any, name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    value = job.parameters.get(name)
    if value is None:
        return default
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")
    return tuple(item.strip() for item in value if item.strip())


def _graph(job: Any, data: ChronicleInput):
    declared = _tuple_param(job, "name_fields")
    extra: dict[str, Any] = {"name_fields": declared} if declared else {}
    return build_entity_graph(
        data.source_ids,
        data.texts,
        known_names=_tuple_param(job, "known_names"),
        match_surnames=bool(job.parameters.get("match_surnames", False)),
        **extra,
    )


def _mentions(graph) -> dict[str, tuple[str, ...]]:
    return {item.entity_id: (item.canonical, *item.aliases) for item in graph.entities}


def _coverage(data: ChronicleInput, cited: set[str]) -> Coverage:
    return compute_coverage(
        all_source_ids=data.source_ids,
        read_source_ids=data.texts,
        cited_source_ids=cited,
    )


def _json_artifact(output: Path, name: str, payload: dict[str, object], kind: str):
    return write_text_artifact(
        output / name, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        kind,
    )


def _svg_artifact(output: Path, name: str, figure, kind: str) -> ArtifactRecord:
    return write_text_artifact(output / name, figure.svg, kind)


def _report(
    job: Any,
    output: Path,
    basename: str,
    title: str,
    claims: tuple[Claim, ...],
    coverage: Coverage,
) -> list[ArtifactRecord]:
    """Render the findings, and say so honestly when there are none."""
    formats = tuple(job.parameters.get("formats", ["md"]))
    if not claims:
        return [
            write_text_artifact(
                output / f"{basename}.md",
                f"# {title}\n\nThe approved sources carry nothing that answers this "
                "contract. That is the finding, not a missing file.\n",
                "findings-empty",
            )
        ]
    return list(
        render_report_formats(
            ReportDocument(title=title, claims=claims, coverage=coverage),
            output,
            basename=basename,
            formats=formats,
        )
    )


# --------------------------------------------------------------------------- #
# K5 workflows
# --------------------------------------------------------------------------- #


def execute_person_registry(
    job: Any, data: ChronicleInput, run_id: str
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    """Who appears in this corpus, in an identified and a pseudonymous form."""
    graph = _graph(job, data)
    output = Path(job.output_dir)
    identified = registry_payload(graph, pseudonymous=False)
    pseudonymous = registry_payload(graph, pseudonymous=True)
    artifacts = [
        _json_artifact(output, f"{run_id}.person-registry.json", identified, "person-registry"),
        _json_artifact(
            output,
            f"{run_id}.person-registry.pseudonymous.json",
            pseudonymous,
            "person-registry-pseudonymous",
        ),
        _json_artifact(
            output,
            f"{run_id}.identity-map.json",
            {
                "schema": "nemofold.identity-map.v1",
                "note": (
                    "Local re-identification only. This file is what makes the "
                    "pseudonymous registry safe to hand over, and it is the one file "
                    "that must not travel with it."
                ),
                "map": graph.identity_map,
            },
            "identity-map",
        ),
    ]
    claims = tuple(
        Claim(
            statement=f"{entity.canonical} is named in {len(entity.source_ids)} source(s).",
            evidence=tuple(
                EvidenceLocator(
                    source_id=mention.anchor.source_id,
                    quote=mention.quote,
                    section=f"line {mention.anchor.line}",
                )
                for mention in entity.mentions[:3]
            ),
        )
        for entity in graph.entities
    )
    cited = {mention.anchor.source_id for entity in graph.entities for mention in entity.mentions}
    coverage = _coverage(data, cited)
    artifacts.extend(
        _report(job, output, f"{run_id}_registry", "Personenregister", claims, coverage)
    )
    metadata: dict[str, object] = {
        "person_count": len(graph.entities),
        "pseudonymous_export": f"{run_id}.person-registry.pseudonymous.json",
        "identity_map_is_local_only": True,
        "notes": list(graph.notes),
        "no_legal_conclusion": NO_LEGAL_CONCLUSION,
    }
    actions = (
        f"resolved {len(graph.entities)} declared person(s) and wrote an identified, "
        "a pseudonymous and a local identity-map artifact",
    )
    return actions, tuple(artifacts), coverage, metadata


def execute_relation_model(
    job: Any, data: ChronicleInput, run_id: str
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    """Which links between those people a sentence actually states."""
    graph = _graph(job, data)
    output = Path(job.output_dir)
    pseudonymous = bool(job.parameters.get("pseudonymous", False))
    labels = {
        item.entity_id: (item.entity_id if pseudonymous else item.canonical)
        for item in graph.entities
    }
    figure = relation_graph_svg(
        tuple((item.entity_id, labels[item.entity_id]) for item in graph.entities),
        tuple(
            (item.subject, item.object, item.kind, "" if pseudonymous else item.quote)
            for item in graph.relations
        ),
    )
    artifacts = [
        _json_artifact(
            output,
            f"{run_id}.relations.json",
            registry_payload(graph, pseudonymous=pseudonymous),
            "relation-model",
        ),
        _svg_artifact(output, f"{run_id}.relations.svg", figure, "relation-graph"),
    ]
    claims = tuple(
        Claim(
            statement=(
                f"{labels.get(item.subject, item.subject)} and "
                f"{labels.get(item.object, item.object)}: {item.kind}"
            ),
            evidence=(
                EvidenceLocator(
                    source_id=item.anchor.source_id,
                    quote=item.quote,
                    section=f"line {item.anchor.line}",
                ),
            ),
        )
        for item in graph.relations
    )
    metadata: dict[str, object] = {
        "relation_count": len(graph.relations),
        "typed_relation_count": sum(1 for item in graph.relations if item.typed),
        "figure_description": figure.description,
        "edge_rule": (
            "An edge exists only where a sentence states it. Co-mention means the two "
            "people are named in one sentence and nothing more."
        ),
        "no_legal_conclusion": NO_LEGAL_CONCLUSION,
    }
    cited = {item.anchor.source_id for item in graph.relations}
    coverage = _coverage(data, cited)
    artifacts.extend(
        _report(job, output, f"{run_id}_relations", "Beziehungsmodell", claims, coverage)
    )
    actions = (f"derived {len(graph.relations)} stated edge(s) and rendered the graph",)
    return actions, tuple(artifacts), coverage, metadata


# --------------------------------------------------------------------------- #
# K4 workflows
# --------------------------------------------------------------------------- #


def _timeline_artifacts(
    output: Path, run_id: str, timeline, title: str, lanes
) -> tuple[list[ArtifactRecord], Any]:
    figure = timeline_svg(lanes, title=title)
    return (
        [
            _json_artifact(
                output, f"{run_id}.timeline.json", timeline_payload(timeline, title=title),
                "timeline",
            ),
            _svg_artifact(output, f"{run_id}.timeline.svg", figure, "timeline-figure"),
        ],
        figure,
    )


def _timeline_claims(timeline) -> tuple[Claim, ...]:
    return tuple(
        Claim(
            statement=(
                f"{event.start.raw}: {event.label}"
                if event.determined
                else f"undetermined time ({event.start.raw}): {event.label}"
            ),
            evidence=(
                EvidenceLocator(
                    source_id=event.anchor.source_id,
                    quote=event.quote,
                    section=f"line {event.anchor.line}",
                ),
            ),
        )
        for event in timeline.events
    )


def execute_person_timeline(
    job: Any, data: ChronicleInput, run_id: str
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    """One lane per declared person, with undetermined times kept undetermined."""
    graph = _graph(job, data)
    names = graph.identity_map
    timeline = extract_events(data.source_ids, data.texts, mentions=_mentions(graph))
    lanes = []
    for entity_id in sorted(names):
        entries = tuple(
            (
                event.label,
                _minutes(event.start.value) or 0,
                _minutes(event.end.value) if event.end else None,
                event.determined,
            )
            for event in timeline.for_subject(entity_id)
        )
        if entries:
            lanes.append((names[entity_id], entries))
    unattributed = tuple(
        (
            event.label,
            _minutes(event.start.value) or 0,
            _minutes(event.end.value) if event.end else None,
            event.determined,
        )
        for event in timeline.events
        if not event.subject
    )
    if unattributed:
        # Events nobody could be attributed to are still shown, in their own lane.
        lanes.append(("(nicht zugeordnet)", unattributed))
    output = Path(job.output_dir)
    artifacts, figure = _timeline_artifacts(
        output, run_id, timeline, str(job.parameters.get("title") or "Personen-Zeitachse"),
        tuple(lanes),
    )
    metadata: dict[str, object] = {
        "event_count": len(timeline.events),
        "undetermined_count": len(timeline.undetermined),
        "lane_count": len(lanes),
        "figure_description": figure.description,
        "notes": list(timeline.notes),
        "no_legal_conclusion": NO_LEGAL_CONCLUSION,
    }
    cited = {event.anchor.source_id for event in timeline.events}
    coverage = _coverage(data, cited)
    artifacts.extend(
        _report(
            job, output, f"{run_id}_timeline", "Personen-Zeitachse",
            _timeline_claims(timeline), coverage,
        )
    )
    actions = (
        f"placed {len(timeline.events)} stated event(s) on {len(lanes)} lane(s); "
        f"{len(timeline.undetermined)} stayed undetermined",
    )
    return actions, tuple(artifacts), coverage, metadata


def execute_coverage_timeline(
    job: Any, data: ChronicleInput, run_id: str
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    """When somebody was covered, read from declared contract fields only."""
    timeline = extract_coverage(
        data.source_ids,
        data.texts,
        start_field=str(job.parameters.get("start_field", "Deckung ab")),
        end_field=str(job.parameters.get("end_field", "Deckung bis")),
        label_field=str(job.parameters.get("label_field", "Tarif")),
        holder_field=str(job.parameters.get("holder_field", "Versicherungsnehmer")),
    )
    lanes = tuple(
        (
            f"{event.label} · {event.subject}" if event.subject else event.label,
            (
                (
                    event.label,
                    _minutes(event.start.value) or 0,
                    _minutes(event.end.value) if event.end else None,
                    event.determined,
                ),
            ),
        )
        for event in timeline.events
    )
    output = Path(job.output_dir)
    valid_events = tuple(e for e in timeline.events if e.determined)
    min_intervals = job.parameters.get("min_intervals")
    require_complete = bool(job.parameters.get("require_complete_coverage", False))
    coverage_missing = (
        min_intervals is not None and len(valid_events) < int(min_intervals)
    ) or (require_complete and len(valid_events) < len(data.source_ids))
    if coverage_missing:
        target_count = int(min_intervals) if min_intervals is not None else len(data.source_ids)
        question = Question(
            field="coverage_dates",
            prompt=(
                f"Keine ausreichenden Deckungszeiträume gefunden "
                f"({len(valid_events)} < {target_count}). "
                "Bitte prüfen Sie die Vertragsdokumente auf deklarierte Datumsangaben."
            ),
            why=(
                "Fehlende Vertragsdaten erzeugen Unsicherheitshinweise statt erfundener "
                "Abdeckung; ohne deklarierte Deckungsdaten kann keine Zeitachse gezeichnet werden."
            ),
            kind="text",
        )
        asked = needs_input_payload((question,), workflow=job.workflow)
        needs_artifact = write_text_artifact(
            output / f"{run_id}.needs-user-input.json",
            json.dumps(asked, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "needs-user-input",
        )
        coverage = _coverage(data, set())
        raise WorkflowBlocked(
            (f"insufficient_coverage_intervals:{len(valid_events)}<{target_count}",),
            actions=(f"analyzed {len(data.source_ids)} source(s)", "coverage_intervals_missing"),
            artifacts=(needs_artifact,),
            coverage=coverage,
            metadata={
                "interval_count": len(valid_events),
                "undetermined_count": len(timeline.undetermined),
                "target_interval_count": target_count,
                "needs_user_input": True,
                "outcome_note": asked["outcome_note"],
                "notes": list(timeline.notes),
            },
        )
    artifacts, figure = _timeline_artifacts(
        output, run_id, timeline, str(job.parameters.get("title") or "Versicherungsverlauf"),
        lanes,
    )
    metadata: dict[str, object] = {
        "interval_count": len(timeline.events),
        "figure_description": figure.description,
        "notes": list(timeline.notes),
        "open_end_note": (
            "A contract that names no end date is drawn with an open end. Filling it "
            "in would be deciding when somebody was covered."
        ),
        "no_legal_conclusion": NO_LEGAL_CONCLUSION,
    }
    cited = {event.anchor.source_id for event in timeline.events}
    coverage = _coverage(data, cited)
    artifacts.extend(
        _report(
            job, output, f"{run_id}_coverage", "Versicherungsverlauf",
            _timeline_claims(timeline), coverage,
        )
    )
    actions = (f"read {len(timeline.events)} declared coverage interval(s)",)
    return actions, tuple(artifacts), coverage, metadata


def execute_cost_timeline(
    job: Any, data: ChronicleInput, run_id: str
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    """Plan recurring and irregular costs from declared contract fields.

    Normalizes billing cadences and due dates, projects upcoming period totals,
    and keeps unknown due dates separate rather than guessing exact moments.
    """
    cost_timeline = extract_costs(
        data.source_ids,
        data.texts,
        contract_field=str(job.parameters.get("contract_field", "Vertrag")),
        amount_field=str(job.parameters.get("amount_field", "Betrag")),
        cadence_field=str(job.parameters.get("cadence_field", "Turnus")),
        due_date_field=str(job.parameters.get("due_date_field", "Nächste Fälligkeit")),
        category_field=str(job.parameters.get("category_field", "Kategorie")),
    )
    output = Path(job.output_dir)

    min_items = job.parameters.get("min_cost_items")
    if min_items is not None and len(cost_timeline.items) < int(min_items):
        question = Question(
            field="cost_items",
            prompt=(
                f"Keine ausreichenden Kostenpositionen gefunden "
                f"({len(cost_timeline.items)} < {min_items}). "
                "Bitte prüfen Sie die Vertragsdokumente auf deklarierte Kosten."
            ),
            why=(
                "Fehlende Vertragsdaten erzeugen Unsicherheitshinweise statt erfundener "
                "Kostenpositionen; ohne deklarierte Kosten kann keine Kostenplanung erfolgen."
            ),
            kind="text",
        )
        asked = needs_input_payload((question,), workflow=job.workflow)
        needs_artifact = write_text_artifact(
            output / f"{run_id}.needs-user-input.json",
            json.dumps(asked, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "needs-user-input",
        )
        coverage = _coverage(data, set())
        raise WorkflowBlocked(
            (f"insufficient_cost_items:{len(cost_timeline.items)}<{min_items}",),
            actions=(f"analyzed {len(data.source_ids)} source(s)", "cost_items_missing"),
            artifacts=(needs_artifact,),
            coverage=coverage,
            metadata={
                "item_count": len(cost_timeline.items),
                "target_item_count": min_items,
                "needs_user_input": True,
                "outcome_note": asked["outcome_note"],
            },
        )

    require_deterministic = bool(job.parameters.get("require_deterministic_due_dates", False))
    undetermined_items = tuple(item for item in cost_timeline.items if not item.determined)
    if require_deterministic and undetermined_items:
        contracts_list = ", ".join(item.contract for item in undetermined_items)
        question = Question(
            field="cost_due_dates",
            prompt=(
                f"Unbekannte oder unvollständige Fälligkeiten für {len(undetermined_items)} "
                f"Vertrag/Verträge gefunden ({contracts_list}). "
                "Unbekannte Fälligkeiten dürfen nicht als exakte Prognosen dargestellt werden. "
                "Bitte tragen Sie die Fälligkeiten nach."
            ),
            why=(
                "Unbekannte Fälligkeiten werden nicht als exakte Prognosen dargestellt; "
                "ohne belegte Fälligkeit kann kein exaktes Fälligkeitsdatum prognostiziert werden."
            ),
            kind="text",
        )
        asked = needs_input_payload((question,), workflow=job.workflow)
        needs_artifact = write_text_artifact(
            output / f"{run_id}.needs-user-input.json",
            json.dumps(asked, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "needs-user-input",
        )
        coverage = _coverage(data, set())
        raise WorkflowBlocked(
            (f"undetermined_cost_due_dates:{len(undetermined_items)}",),
            actions=(f"analyzed {len(data.source_ids)} source(s)", "cost_due_dates_undetermined"),
            artifacts=(needs_artifact,),
            coverage=coverage,
            metadata={
                "undetermined_count": len(undetermined_items),
                "undetermined_contracts": [item.contract for item in undetermined_items],
                "needs_user_input": True,
                "outcome_note": asked["outcome_note"],
            },
        )

    forecast_month = job.parameters.get("forecast_month")
    projected_recurring_total = 0.0
    projected_special_effects_total = 0.0
    for item in cost_timeline.items:
        if not item.determined or item.amount is None:
            continue
        if forecast_month:
            if item.cadence == "monthly":
                projected_recurring_total += item.amount
            elif item.due_date.value and item.due_date.value.startswith(forecast_month):
                if (
                    item.category == "special_effect"
                    or item.cadence in ("annual", "biennial", "irregular")
                ):
                    projected_special_effects_total += item.amount
                else:
                    projected_recurring_total += item.amount
        else:
            if (
                item.category == "special_effect"
                or item.cadence in ("annual", "biennial", "irregular")
            ):
                projected_special_effects_total += item.amount
            else:
                projected_recurring_total += item.amount

    recurring_entries = []
    special_entries = []
    undetermined_entries = []
    for item in cost_timeline.items:
        entry = (
            f"{item.contract}: {item.amount_raw}" if item.amount_raw else item.contract,
            _minutes(item.due_date.value) or 0,
            None,
            item.determined,
        )
        if not item.determined:
            undetermined_entries.append(entry)
        elif (
            item.category == "special_effect"
            or item.cadence in ("annual", "biennial", "irregular")
        ):
            special_entries.append(entry)
        else:
            recurring_entries.append(entry)

    lanes = []
    if recurring_entries:
        lanes.append(("Wiederkehrende Kosten", tuple(recurring_entries)))
    if special_entries:
        lanes.append(("Erwartbare Sondereffekte", tuple(special_entries)))
    if undetermined_entries:
        lanes.append(("(Unbestimmte Fälligkeiten)", tuple(undetermined_entries)))

    title = str(job.parameters.get("title") or "Kosten- und Fälligkeitsplanung")
    payload = cost_timeline_payload(
        cost_timeline,
        title=title,
        forecast_month=str(forecast_month) if forecast_month else None,
        projected_recurring_total=projected_recurring_total,
        projected_special_effects_total=projected_special_effects_total,
        undetermined_items=undetermined_items,
    )
    figure = timeline_svg(tuple(lanes), title=title)
    artifacts: list[ArtifactRecord] = [
        _json_artifact(output, f"{run_id}.timeline.json", payload, "cost-timeline"),
        _svg_artifact(output, f"{run_id}.timeline.svg", figure, "timeline-figure"),
    ]

    claims: list[Claim] = []
    for item in cost_timeline.items:
        statement = (
            f"{item.contract}: {item.amount_raw} ({item.cadence_raw}), "
            f"Fälligkeit {item.due_date.value or item.due_date.raw}"
        )
        claims.append(
            Claim(
                statement=statement,
                evidence=(
                    EvidenceLocator(
                        source_id=item.anchor.source_id,
                        quote=item.quote,
                        section=f"line {item.anchor.line}",
                    ),
                ),
            )
        )

    cited = {item.anchor.source_id for item in cost_timeline.items}
    coverage = _coverage(data, cited)
    artifacts.extend(
        _report(
            job,
            output,
            f"{run_id}_cost_plan",
            title,
            tuple(claims),
            coverage,
        )
    )
    metadata: dict[str, object] = {
        "item_count": len(cost_timeline.items),
        "undetermined_count": len(undetermined_items),
        "forecast_month": forecast_month,
        "projected_total": round(
            projected_recurring_total + projected_special_effects_total, 2
        ),
        "projected_recurring_total": round(projected_recurring_total, 2),
        "projected_special_effects_total": round(projected_special_effects_total, 2),
        "figure_description": figure.description,
        "notes": list(cost_timeline.notes),
        "honesty_note": (
            "Wiederkehrende Kosten und erwartbare Sondereffekte werden mit Zeitraum und "
            "Quelle ausgewiesen. Unbekannte Fälligkeiten werden nicht als exakte Prognosen "
            "dargestellt."
        ),
        "no_legal_conclusion": NO_LEGAL_CONCLUSION,
    }
    actions = (
        f"analyzed {len(cost_timeline.items)} cost item(s); "
        f"projected {len(cost_timeline.items) - len(undetermined_items)} confirmed item(s)",
    )
    return actions, tuple(artifacts), coverage, metadata


# --------------------------------------------------------------------------- #
# K6 workflows
# --------------------------------------------------------------------------- #


def execute_alibi_weave(
    job: Any, data: ChronicleInput, run_id: str
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    """Self-reports on one line, outside confirmation on a second, gaps hatched."""
    graph = _graph(job, data)
    names = graph.identity_map
    weave = weave_alibis(
        data.source_ids,
        data.texts,
        _mentions(graph),
        places=_tuple_param(job, "places"),
        tolerance_minutes=int(job.parameters.get("tolerance_minutes", 90)),
    )
    window = str(job.parameters.get("window") or "the approved sources")
    figure = alibi_weave_svg(
        tuple(
            (
                names.get(item.position.subject, item.position.subject),
                item.position.place,
                _minutes(item.position.time.value),
                len(item.confirmations),
            )
            for item in weave.supported
        ),
        tuple((names.get(gap.subject, gap.subject), gap.reason) for gap in weave.gaps),
        title=str(job.parameters.get("title") or "Alibi-Gewebe"),
    )
    output = Path(job.output_dir)
    artifacts = [
        _json_artifact(
            output, f"{run_id}.alibi-weave.json", weave_payload(weave, window=window), "alibi-weave"
        ),
        _svg_artifact(output, f"{run_id}.alibi-weave.svg", figure, "alibi-figure"),
    ]
    claims = tuple(
        Claim(
            statement=(
                f"{names.get(item.position.subject, item.position.subject)} at "
                f"{item.position.place}: {item.level}"
            ),
            evidence=(
                EvidenceLocator(
                    source_id=item.position.anchor.source_id,
                    quote=item.position.quote,
                    section=f"line {item.position.anchor.line}",
                ),
                *(
                    EvidenceLocator(
                        source_id=confirmation.by_source,
                        quote=confirmation.naming_quote,
                        section=f"line {confirmation.naming_anchor.line}",
                    )
                    for confirmation in item.confirmations
                ),
            ),
        )
        for item in weave.supported
    )
    suggestions = (
        suggest_places(data.source_ids, data.texts)
        if not _tuple_param(job, "places")
        else ()
    )
    metadata: dict[str, object] = {
        "suggested_places": [
            {"place": place, "mentions": count} for place, count in suggestions
        ],
        "suggestion_note": (
            "These are candidates read out of the corpus, not a default. Confirm the "
            "ones you mean in the places parameter; a vocabulary this run chose for "
            "you would quietly decide who counts as corroborated."
        ),
        "position_count": len(weave.supported),
        "corroborated_count": weave.corroborated_count,
        "gap_count": len(weave.gaps),
        "figure_description": figure.description,
        "notes": list(weave.notes),
        "no_legal_conclusion": NO_LEGAL_CONCLUSION,
    }
    cited = {item.position.anchor.source_id for item in weave.supported}
    coverage = _coverage(data, cited)
    artifacts.extend(_report(job, output, f"{run_id}_weave", "Alibi-Gewebe", claims, coverage))
    actions = (
        f"rated {len(weave.supported)} stated position(s), {weave.corroborated_count} "
        f"confirmed by another source, and reported {len(weave.gaps)} gap(s)",
    )
    return actions, tuple(artifacts), coverage, metadata


# --------------------------------------------------------------------------- #
# K7 workflow
# --------------------------------------------------------------------------- #


def execute_corpus_query(
    job: Any, data: ChronicleInput, run_id: str
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    """A needle question over a large bundle, answered only in quotes."""
    terms = _tuple_param(job, "terms") or tuple(job.questions)
    if not terms:
        raise ValueError("corpus_query needs a question or a terms parameter")
    statements: tuple[AnchoredStatement, ...] = _statements(
        data.source_ids,
        data.texts,
        focus_terms=terms,
        max_per_source=int(job.parameters.get("max_per_source", 200)),
    )
    outcome = aggregate_mapreduce(
        statements,
        scope=str(job.parameters.get("dedupe_scope", "normalized")),
        budget=AggregationBudget(
            partition_size=int(job.parameters.get("partition_size", 20)),
            max_results=int(job.parameters.get("max_results", 200)),
        ),
    )
    output = Path(job.output_dir)
    min_matches = int(job.parameters.get("min_matches", 0))
    max_matches_val = job.parameters.get("max_matches")
    max_matches = None if max_matches_val is None else int(max_matches_val)

    if min_matches > 0 and len(outcome.results) < min_matches:
        question = Question(
            field="terms",
            prompt=(
                f"Kein Beleg für {', '.join(terms)} gefunden. "
                "Möchten Sie nach einem anderen Begriff suchen?"
            ),
            why="Die Korpus-Suche ergab keine Fundstellen im bereitgestellten Dokumentenbestand.",
            kind="search_term",
        )
        asked = needs_input_payload((question,), workflow=job.workflow)
        needs_artifact = write_text_artifact(
            output / f"{run_id}.needs-user-input.json",
            json.dumps(asked, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "needs-user-input",
        )
        coverage = _coverage(data, set())
        raise WorkflowBlocked(
            (f"no_matches_found:{','.join(terms)}",),
            actions=(f"searched {len(data.source_ids)} source(s)", "no_matches_found"),
            artifacts=(needs_artifact,),
            coverage=coverage,
            metadata={
                "terms": list(terms),
                "match_count": len(outcome.results),
                "needs_user_input": True,
                "outcome_note": asked["outcome_note"],
            },
        )

    if max_matches is not None and len(outcome.results) > max_matches:
        question = Question(
            field="document_choice",
            prompt=(
                f"Mehrdeutige Fundstellen ({len(outcome.results)} Treffer für {', '.join(terms)}). "
                "Bitte wählen Sie das maßgebliche Dokument."
            ),
            why="Es wurden mehrere unterschiedliche Belege gefunden, die geklärt werden müssen.",
            kind="document_selection",
        )
        asked = needs_input_payload((question,), workflow=job.workflow)
        needs_artifact = write_text_artifact(
            output / f"{run_id}.needs-user-input.json",
            json.dumps(asked, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "needs-user-input",
        )
        cited = {anchor.source_id for item in outcome.results for anchor in item.anchors}
        coverage = _coverage(data, cited)
        raise WorkflowBlocked(
            (f"ambiguous_matches:{len(outcome.results)}>{max_matches}",),
            actions=(f"searched {len(data.source_ids)} source(s)", "ambiguous_matches_found"),
            artifacts=(needs_artifact,),
            coverage=coverage,
            metadata={
                "terms": list(terms),
                "match_count": len(outcome.results),
                "needs_user_input": True,
                "outcome_note": asked["outcome_note"],
            },
        )
    payload = {
        "schema": "nemofold.corpus-query.v1",
        "terms": list(terms),
        "match_count": len(outcome.results),
        "partition_count": outcome.partition_count,
        "stages": [
            {
                "name": stage.name,
                "inputs": stage.inputs,
                "outputs": stage.outputs,
                "dropped": stage.dropped,
            }
            for stage in outcome.stages
        ],
        "matches": [
            {
                "statement": item.text,
                "support": item.support,
                "anchor_total": item.anchor_total,
                "anchors": [
                    {"source_id": anchor.source_id, "line": anchor.line}
                    for anchor in item.anchors
                ],
            }
            for item in outcome.results
        ],
        "notes": list(outcome.notes),
        "quote_rule": (
            "Every match is a sentence lifted from a source. Nothing here is a summary, "
            "so an answer with no match means the corpus does not contain one."
        ),
    }
    artifacts = [_json_artifact(output, f"{run_id}.corpus-query.json", payload, "corpus-query")]
    claims = tuple(
        Claim(
            statement=item.text,
            evidence=tuple(
                EvidenceLocator(
                    source_id=anchor.source_id, quote=item.text, section=f"line {anchor.line}"
                )
                for anchor in item.anchors[:4]
            ),
        )
        for item in outcome.results
    )
    cited = {anchor.source_id for item in outcome.results for anchor in item.anchors}
    metadata: dict[str, object] = {
        "terms": list(terms),
        "match_count": len(outcome.results),
        "partition_count": outcome.partition_count,
        "within_budget": outcome.within_budget,
        "notes": list(outcome.notes),
        "no_legal_conclusion": NO_LEGAL_CONCLUSION,
    }
    coverage = _coverage(data, cited)
    artifacts.extend(_report(job, output, f"{run_id}_query", "Korpus-Suche", claims, coverage))
    actions = (
        f"searched {len(data.source_ids)} source(s) in {outcome.partition_count} "
        f"partition(s) and kept {len(outcome.results)} quoted match(es)",
    )
    return actions, tuple(artifacts), coverage, metadata


# --------------------------------------------------------------------------- #
# The contradiction synopsis
# --------------------------------------------------------------------------- #


def execute_contradiction_synopsis(
    job: Any, data: ChronicleInput, run_id: str
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    """Put disagreeing statements side by side, in both wordings, with anchors.

    A synopsis that resolves a contradiction has destroyed the finding. Both
    readings stay, each with the source and line that carries it, and the report
    says which two sources disagree rather than which one is right.
    """
    merged = merge_sections(data.source_ids, data.texts)
    terms = _tuple_param(job, "contested_terms")
    contested: list[dict[str, object]] = []
    if terms:
        # A declared contested term - a colour, a vehicle, a place - is compared
        # across sources by lifting every sentence that mentions it.
        for term in terms:
            statements = _statements(
                data.source_ids, data.texts, focus_terms=(term,), max_per_source=40
            )
            sources = {item.anchor.source_id for item in statements}
            if len(sources) < 2:
                continue
            contested.append(
                {
                    "term": term,
                    "readings": [
                        {
                            "source_id": item.anchor.source_id,
                            "line": item.anchor.line,
                            "quote": item.text,
                        }
                        for item in statements
                    ],
                }
            )
    payload = {
        "schema": "nemofold.contradiction-synopsis.v1",
        "label_conflict_count": len(merged.conflicts),
        "contested_term_count": len(contested),
        "label_conflicts": [
            {
                "section": conflict.section,
                "label": conflict.label,
                "readings": [
                    {"value": value, "source_id": anchor.source_id, "line": anchor.line}
                    for value, anchor in conflict.values
                ],
            }
            for conflict in merged.conflicts
        ],
        "contested_terms": contested,
        "synopsis_rule": (
            "Both wordings stay. This report names which sources disagree and where; "
            "it does not decide which of them is right."
        ),
    }
    output = Path(job.output_dir)
    artifacts = [
        _json_artifact(output, f"{run_id}.contradictions.json", payload, "contradiction-synopsis")
    ]
    claims: list[Claim] = []
    for conflict in merged.conflicts:
        claims.append(
            Claim(
                statement=f"{conflict.section} · {conflict.label}: sources disagree",
                evidence=tuple(
                    EvidenceLocator(
                        source_id=anchor.source_id, quote=value, section=f"line {anchor.line}"
                    )
                    for value, anchor in conflict.values
                ),
            )
        )
    for item in contested:
        readings = item["readings"]
        assert isinstance(readings, list)
        claims.append(
            Claim(
                statement=f"'{item['term']}' is described differently across sources",
                evidence=tuple(
                    EvidenceLocator(
                        source_id=str(reading["source_id"]),
                        quote=str(reading["quote"]),
                        section=f"line {reading['line']}",
                    )
                    for reading in readings[:6]
                ),
            )
        )
    cited = {
        anchor.source_id for conflict in merged.conflicts for _, anchor in conflict.values
    }
    for item in contested:
        readings = item["readings"]
        assert isinstance(readings, list)
        cited |= {str(reading["source_id"]) for reading in readings}
    coverage = _coverage(data, cited)
    artifacts.extend(
        _report(job, output, f"{run_id}_contradictions", "Widerspruchs-Synopse",
                tuple(claims), coverage)
    )
    metadata: dict[str, object] = {
        "label_conflict_count": len(merged.conflicts),
        "contested_term_count": len(contested),
        "no_legal_conclusion": NO_LEGAL_CONCLUSION,
        "synopsis_rule": payload["synopsis_rule"],
    }
    actions = (
        f"found {len(merged.conflicts)} label conflict(s) and {len(contested)} contested "
        "term(s), and kept both readings of each",
    )
    return actions, tuple(artifacts), coverage, metadata
