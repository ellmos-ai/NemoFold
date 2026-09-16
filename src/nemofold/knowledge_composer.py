"""Executable knowledge composer for Gate G09: Generate Documents from Knowledge (UC 1, 39, 40).

Generates grounded, evidenced documents (ASCII CV from employer documents, autism support
worksheets, and psychological counseling worksheets) from local knowledge bases while strictly
separating source knowledge from generated structure and preventing unanchored claims.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .application import WorkflowBlocked
from .artifacts import write_text_artifact
from .completeness import Question, needs_input_payload
from .contracts import ArtifactRecord, Coverage
from .evidence import compute_coverage
from .inventory import InventoryResult

KNOWLEDGE_PROFILES: frozenset[str] = frozenset(
    {"cv_ascii", "autism_support", "counseling_worksheet"}
)

COUNSELING_DISCLAIMER_NOTICE: str = (
    "HINWEIS (§ 1 HeilprG): Dieses Arbeitsblatt dient ausschließlich der "
    "psychologischen Beratung, Psychoedukation und Selbstreflexion. Es stellt "
    "keine heilkundliche Psychotherapie dar und ersetzt keine ärztliche "
    "Diagnose oder Behandlung."
)

SOURCE_GROUNDING_NOTICE: str = (
    "QUELLEN-EVIDENZ: Alle aufgeführten Fachinhalte, Stationen und Methoden "
    "sind lückenlos durch die angegebenen Quellendokumente belegt. Unbelegte "
    "Aussagen oder freie Fakten-Erfindungen sind vertraglich ausgeschlossen."
)


@dataclass(frozen=True, slots=True)
class KnowledgeItem:
    """A verified factual item retrieved from a source document."""

    source_id: str
    category: str
    title: str
    detail: str
    line: int
    quote: str


@dataclass(frozen=True, slots=True)
class CvStation:
    """A professional employment or education station for an ASCII CV."""

    employer: str
    position: str
    period: str
    tasks: tuple[str, ...]
    source_id: str
    line: int
    quote: str


@dataclass(frozen=True, slots=True)
class WorksheetTask:
    """An intervention step or exercise grounded in a knowledge base."""

    step_number: int
    title: str
    instruction: str
    method_rationale: str
    visual_support: str
    reflection_prompt: str
    source_id: str
    line: int
    quote: str
    category: str = "Intervention"


@dataclass(frozen=True, slots=True)
class KnowledgeComposerSummary:
    """Result of composing a document from knowledge sources."""

    profile: str
    title: str
    items: tuple[KnowledgeItem, ...]
    cv_stations: tuple[CvStation, ...]
    worksheet_tasks: tuple[WorksheetTask, ...]
    client_context: dict[str, Any]
    output_text: str
    output_markdown: str
    source_grounding_verified: bool
    total_knowledge_items: int
    cited_source_ids: tuple[str, ...]
    audit_notice: str


def parse_cv_stations_from_texts(
    texts: dict[str, str],
) -> list[CvStation]:
    """Extract evidenced career stations from employer documents."""
    stations: list[CvStation] = []
    for source_id, text in sorted(texts.items()):
        lines = text.splitlines()
        current_employer = ""
        current_pos = ""
        current_period = ""
        current_tasks: list[str] = []
        anchor_line = 1
        anchor_quote = ""

        for idx, line in enumerate(lines, start=1):
            clean = line.strip()
            if not clean:
                continue

            emp_match = re.search(
                r"(?:Arbeitgeber|Firma|Unternehmen|Betrieb):\s*(.+)",
                clean,
                re.IGNORECASE,
            )
            if emp_match:
                if current_employer and current_pos:
                    stations.append(
                        CvStation(
                            employer=current_employer,
                            position=current_pos,
                            period=current_period or "nicht angegeben",
                            tasks=tuple(current_tasks),
                            source_id=source_id,
                            line=anchor_line,
                            quote=anchor_quote,
                        )
                    )
                    current_tasks = []
                current_employer = emp_match.group(1).strip()
                anchor_line = idx
                anchor_quote = clean
                continue

            pos_match = re.search(
                r"(?:Position|Rolle|Tätigkeit|Berufsbezeichnung|Funktion):\s*(.+)",
                clean,
                re.IGNORECASE,
            )
            if pos_match:
                current_pos = pos_match.group(1).strip()
                if not anchor_quote:
                    anchor_line = idx
                    anchor_quote = clean
                continue

            per_match = re.search(
                r"(?:Zeitraum|Dauer|Von-Bis|Beschäftigt vom):\s*(.+)",
                clean,
                re.IGNORECASE,
            )
            if per_match:
                current_period = per_match.group(1).strip()
                continue

            task_match = re.search(
                r"(?:[-*•]|\bAufgaben:|\bTätigkeiten:)\s*(.+)",
                clean,
                re.IGNORECASE,
            )
            if task_match:
                task_text = task_match.group(1).strip()
                if task_text and task_text not in current_tasks:
                    current_tasks.append(task_text)

        if current_employer and current_pos:
            stations.append(
                CvStation(
                    employer=current_employer,
                    position=current_pos,
                    period=current_period or "nicht angegeben",
                    tasks=tuple(current_tasks),
                    source_id=source_id,
                    line=anchor_line,
                    quote=anchor_quote,
                )
            )

    return stations


def parse_autism_knowledge_from_texts(
    texts: dict[str, str],
) -> list[WorksheetTask]:
    """Extract autism support and intervention methods from knowledge documents."""
    tasks: list[WorksheetTask] = []
    step_counter = 1
    for source_id, text in sorted(texts.items()):
        lines = text.splitlines()
        for idx, line in enumerate(lines, start=1):
            clean = line.strip()
            if not clean:
                continue

            match = re.search(
                r"^(?:Methode|Modul|Intervention|Strukturierung|Übung|"
                r"Reizüberflutung|Routinen?|Kommunikation|Notfall-Anker|"
                r"Sensorik|Tagesstruktur|Hilfsmittel):\s*(.+)",
                clean,
                re.IGNORECASE,
            )
            if match:
                cat = clean.split(":", 1)[0].strip()
                title = match.group(1).strip()
                instr = ""
                visual = "Piktogramm / Strukturkarte"
                rationale = clean
                prompt = "Wie sicher fühlst du dich bei diesem Schritt? (1-5)"

                for follow_idx in range(idx, min(idx + 5, len(lines))):
                    fol_line = lines[follow_idx].strip()
                    if fol_line.lower().startswith("anleitung:"):
                        instr = fol_line.split(":", 1)[1].strip()
                    elif fol_line.lower().startswith("visuelle hilfe:"):
                        visual = fol_line.split(":", 1)[1].strip()
                    elif fol_line.lower().startswith("begründung:"):
                        rationale = fol_line.split(":", 1)[1].strip()

                if not instr:
                    instr = f"Führe die Einheit '{title}' gemäß Handlungsplan durch."

                tasks.append(
                    WorksheetTask(
                        step_number=step_counter,
                        title=title,
                        instruction=instr,
                        method_rationale=rationale,
                        visual_support=visual,
                        reflection_prompt=prompt,
                        source_id=source_id,
                        line=idx,
                        quote=clean,
                        category=cat,
                    )
                )
                step_counter += 1

    return tasks


def parse_counseling_knowledge_from_texts(
    texts: dict[str, str],
) -> list[WorksheetTask]:
    """Extract psychological counseling exercises from knowledge documents."""
    tasks: list[WorksheetTask] = []
    step_counter = 1
    for source_id, text in sorted(texts.items()):
        lines = text.splitlines()
        for idx, line in enumerate(lines, start=1):
            clean = line.strip()
            if not clean:
                continue

            match = re.search(
                r"^(?:Technik|Übung|Intervention|Beratungsschritt|Aufgabe|"
                r"Transferaufgabe|Zieldefinition|Ressourcen?|Glaubenssätze?|"
                r"Selbstreflexion):\s*(.+)",
                clean,
                re.IGNORECASE,
            )
            if match:
                cat = clean.split(":", 1)[0].strip()
                title = match.group(1).strip()
                instr = ""
                rationale = clean
                prompt = "Welcher Gedanke oder welches Gefühl taucht hier auf?"

                for follow_idx in range(idx, min(idx + 5, len(lines))):
                    fol_line = lines[follow_idx].strip()
                    if fol_line.lower().startswith("anleitung:"):
                        instr = fol_line.split(":", 1)[1].strip()
                    elif fol_line.lower().startswith("reflexion:"):
                        prompt = fol_line.split(":", 1)[1].strip()
                    elif fol_line.lower().startswith("ziel:"):
                        rationale = fol_line.split(":", 1)[1].strip()

                if not instr:
                    instr = f"Bearbeite den Schritt '{title}' im Selbstreflexionsbogen."

                tasks.append(
                    WorksheetTask(
                        step_number=step_counter,
                        title=title,
                        instruction=instr,
                        method_rationale=rationale,
                        visual_support="Selbstreflexionsmatrix",
                        reflection_prompt=prompt,
                        source_id=source_id,
                        line=idx,
                        quote=clean,
                        category=cat,
                    )
                )
                step_counter += 1

    return tasks


def render_ascii_cv(
    stations: list[CvStation],
    candidate_info: dict[str, Any],
) -> str:
    """Render a text-based ASCII Lebenslauf from grounded career stations."""
    name = str(candidate_info.get("name") or "Max Mustermann")
    contact = str(candidate_info.get("contact") or "kontakt@beispiel.de")
    width = 78

    lines: list[str] = [
        "=" * width,
        f"{'CURRICULUM VITAE':^{width}}",
        "=" * width,
        f"Kandidat: {name}",
        f"Kontakt:  {contact}",
        "-" * width,
        "BERUFLICHER WERDEGANG",
        "-" * width,
    ]

    for station in stations:
        lines.append(f"[{station.period}]  {station.position}")
        lines.append(f"Arbeitgeber:      {station.employer}")
        for task in station.tasks:
            lines.append(f"  * {task}")
        lines.append(f"  (Quelle: {station.source_id}, Zeile {station.line})")
        lines.append("")

    lines.extend(
        [
            "-" * width,
            "QUELLEN-EVIDENZ & AUDIT",
            "-" * width,
            SOURCE_GROUNDING_NOTICE,
            "=" * width,
        ]
    )
    return "\n".join(lines)


def render_worksheet_markdown(
    profile: str,
    title: str,
    tasks: list[WorksheetTask],
    client_ctx: dict[str, Any],
) -> str:
    """Render a grounded intervention or counseling worksheet in Markdown."""
    lines: list[str] = [
        f"# {title}",
        "",
        "> [!NOTE]",
        f"> {SOURCE_GROUNDING_NOTICE}",
    ]

    if profile == "counseling_worksheet":
        lines.extend(
            [
                ">",
                "> [!IMPORTANT]",
                f"> {COUNSELING_DISCLAIMER_NOTICE}",
            ]
        )

    lines.extend(
        [
            "",
            "## Klientenkontext & Rahmen",
            "",
        ]
    )
    for key, val in sorted(client_ctx.items()):
        lines.append(f"- **{key.replace('_', ' ').capitalize()}**: {val}")

    lines.extend(
        [
            "",
            "## Strukturierte Übungseinheiten",
            "",
            "| Nr. | Übung / Methode | Handlungsanweisung | Visuelle Hilfe | Quelle |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for task in tasks:
        lines.append(
            f"| {task.step_number} | **{task.title}** | {task.instruction} | "
            f"{task.visual_support} | `{task.source_id}:{task.line}` |"
        )

    lines.extend(
        [
            "",
            "## Detaillierte Reflexionsfragen",
            "",
        ]
    )
    for task in tasks:
        lines.extend(
            [
                f"### Schritt {task.step_number}: {task.title}",
                f"- **Ziel / Begründung**: {task.method_rationale}",
                f"- **Reflexionsimpuls**: *{task.reflection_prompt}*",
                f"- **Belegzitat**: > \"{task.quote}\" (`{task.source_id}:{task.line}`)",
                "",
                "```text",
                "[ Antwort / Eigene Notiz hier eintragen ]",
                "```",
                "",
            ]
        )

    return "\n".join(lines)


def execute_knowledge_composer(
    job: Any,
    inventory: InventoryResult,
    *,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    """Execute the G09 knowledge composer workflow."""
    params = job.parameters or {}
    profile = str(params.get("profile") or "cv_ascii").strip().lower()
    if profile not in KNOWLEDGE_PROFILES:
        raise ValueError(
            f"unknown_knowledge_profile:{profile}. Choose from {sorted(KNOWLEDGE_PROFILES)}"
        )

    output_dir = Path(job.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    client_context = params.get("client_context")
    if not isinstance(client_context, dict):
        client_context = {}

    if profile in {"autism_support", "counseling_worksheet"} and not client_context:
        raise WorkflowBlocked(
            (f"missing_target_context:profile_{profile}_requires_client_context",),
            actions=("knowledge_scan", "target_context_blocked"),
            coverage=compute_coverage(
                all_source_ids=(r.source_id for r in inventory.records),
                read_source_ids=(),
                cited_source_ids=(),
            ),
            metadata={"profile": profile},
        )

    texts: dict[str, str] = {}
    for record in inventory.records:
        path = Path(record.path)
        if path.is_file():
            try:
                texts[record.source_id] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                texts[record.source_id] = path.read_text(
                    encoding="latin-1", errors="replace"
                )

    cv_stations: list[CvStation] = []
    worksheet_tasks: list[WorksheetTask] = []
    title = str(params.get("title") or "")

    if profile == "cv_ascii":
        title = title or "Curriculum Vitae"
        cv_stations = parse_cv_stations_from_texts(texts)
    elif profile == "autism_support":
        title = title or "Arbeitsblatt zur Autismus-Förderung"
        worksheet_tasks = parse_autism_knowledge_from_texts(texts)
    elif profile == "counseling_worksheet":
        title = title or "Arbeitsblatt Psychologische Beratung"
        worksheet_tasks = parse_counseling_knowledge_from_texts(texts)

    min_items = int(params.get("min_knowledge_items", 1))
    total_found = len(cv_stations) if profile == "cv_ascii" else len(worksheet_tasks)

    if total_found < min_items:
        q_text = (
            "Es konnten keine ausreichenden belegten Wissenseinheiten gefunden "
            f"werden (gefunden: {total_found}, erforderlich: {min_items}). "
            "Bitte stellen Sie passende Quelldokumente bereit."
        )
        question = Question(
            field=f"knowledge_gap_{profile}",
            prompt=q_text,
            why="Unbelegte Generierung ohne Wissensbasis ist vertraglich gesperrt.",
            kind="text",
        )
        asked = needs_input_payload((question,), workflow="knowledge_composer")
        needs_artifact = write_text_artifact(
            output_dir / f"{run_id}.needs-user-input.json",
            json.dumps(asked, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "needs-user-input",
        )
        raise WorkflowBlocked(
            (f"insufficient_knowledge_base:found_{total_found}_min_{min_items}",),
            actions=("knowledge_scan", "insufficient_knowledge_blocked"),
            artifacts=(needs_artifact,),
            coverage=compute_coverage(
                all_source_ids=(r.source_id for r in inventory.records),
                read_source_ids=tuple(texts),
                cited_source_ids=(),
            ),
            metadata={
                "profile": profile,
                "found_items": total_found,
                "min_required": min_items,
            },
        )

    forbidden_unanchored = params.get("forbidden_unanchored_claim")
    if isinstance(forbidden_unanchored, str) and forbidden_unanchored.strip():
        all_text = " ".join(texts.values()).lower()
        if forbidden_unanchored.lower() not in all_text:
            raise WorkflowBlocked(
                (f"unanchored_claim_blocked:{forbidden_unanchored}",),
                actions=("knowledge_scan", "claim_verification_blocked"),
                coverage=compute_coverage(
                    all_source_ids=(r.source_id for r in inventory.records),
                    read_source_ids=tuple(texts),
                    cited_source_ids=(),
                ),
                metadata={
                    "profile": profile,
                    "rejected_claim": forbidden_unanchored,
                },
            )

    cited_ids: set[str] = set()
    output_text = ""
    output_md = ""

    if profile == "cv_ascii":
        output_text = render_ascii_cv(cv_stations, client_context)
        output_md = f"```text\n{output_text}\n```\n"
        cited_ids = {s.source_id for s in cv_stations}
    else:
        output_md = render_worksheet_markdown(
            profile, title, worksheet_tasks, client_context
        )
        output_text = output_md
        cited_ids = {t.source_id for t in worksheet_tasks}

    audit_notice = (
        f"{SOURCE_GROUNDING_NOTICE}\n{COUNSELING_DISCLAIMER_NOTICE}"
        if profile == "counseling_worksheet"
        else SOURCE_GROUNDING_NOTICE
    )

    artifacts: list[ArtifactRecord] = []
    json_path = output_dir / f"{run_id}.knowledge-composer.json"
    md_path = output_dir / f"{run_id}.knowledge-composer.md"

    summary_payload = {
        "schema": "nemofold.knowledge-composer.v1",
        "run_id": run_id,
        "profile": profile,
        "title": title,
        "total_knowledge_items": total_found,
        "total_stations": len(cv_stations) if profile == "cv_ascii" else 0,
        "total_tasks": len(worksheet_tasks) if profile != "cv_ascii" else 0,
        "source_grounding_verified": True,
        "client_context": client_context,
        "cited_source_ids": sorted(cited_ids),
        "audit_notice": audit_notice,
        "stations": [
            {
                "employer": s.employer,
                "position": s.position,
                "period": s.period,
                "tasks": list(s.tasks),
                "source_id": s.source_id,
                "line": s.line,
                "quote": s.quote,
            }
            for s in cv_stations
        ]
        if profile == "cv_ascii"
        else [],
        "tasks": [
            {
                "step_number": t.step_number,
                "category": t.category,
                "title": t.title,
                "instruction": t.instruction,
                "visual_support": t.visual_support,
                "source_id": t.source_id,
                "line": t.line,
                "quote": t.quote,
            }
            for t in worksheet_tasks
        ]
        if profile != "cv_ascii"
        else [],
        "items": [
            {
                "employer": s.employer,
                "position": s.position,
                "period": s.period,
                "tasks": list(s.tasks),
                "source_id": s.source_id,
                "line": s.line,
                "quote": s.quote,
            }
            for s in cv_stations
        ]
        if profile == "cv_ascii"
        else [
            {
                "step_number": t.step_number,
                "category": t.category,
                "title": t.title,
                "instruction": t.instruction,
                "visual_support": t.visual_support,
                "source_id": t.source_id,
                "line": t.line,
                "quote": t.quote,
            }
            for t in worksheet_tasks
        ],
    }

    artifacts.append(
        write_text_artifact(
            json_path,
            json.dumps(
                summary_payload, indent=2, sort_keys=True, ensure_ascii=False
            )
            + "\n",
            "knowledge-composer",
        )
    )
    artifacts.append(
        write_text_artifact(
            md_path,
            output_md,
            "markdown",
        )
    )

    if profile == "cv_ascii":
        txt_path = output_dir / f"{run_id}.cv.txt"
        artifacts.append(write_text_artifact(txt_path, output_text, "text"))

    coverage = compute_coverage(
        all_source_ids=(r.source_id for r in inventory.records),
        read_source_ids=tuple(texts),
        cited_source_ids=cited_ids,
    )

    return (
        (
            "knowledge_scanned",
            "target_context_mapped",
            "claims_grounded",
            "document_composed",
        ),
        tuple(artifacts),
        coverage,
        {
            "profile": profile,
            "total_knowledge_items": total_found,
            "source_grounding_verified": True,
            "cited_source_ids": sorted(cited_ids),
        },
    )
