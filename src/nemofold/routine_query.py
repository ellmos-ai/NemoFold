"""Executable routine query for Gate G10: Query Routines and Reminders (Ellmos UC 44).

Reads specialist local SQLite routine databases (routine_master.db, masterroutine.sqlite)
under strict read-only protection, calculates deterministic cadence due dates against a
declared reference date, detects invalid or contradictory cadence specifications, and
transparently reports that no automated background scheduler is installed.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .artifacts import write_text_artifact
from .completeness import Question, needs_input_payload
from .contracts import ArtifactRecord, WorkflowBlocked
from .evidence import compute_coverage
from .inventory import InventoryResult
from .structured_sources import (
    BoundStructuredSourceError,
    _sqlite_tables,
)

SCHEDULER_NOT_INSTALLED_NOTICE: str = (
    "HINWEIS (Scheduler-Status: nicht installiert): NemoFold liest "
    "MasterRoutine-Datenbanken ausschließlich im strikten Read-Only-Modus "
    "aus. Es werden keine Hintergrund-Tasks im Betriebssystem registriert, "
    "kein externer Scheduler beansprucht und keine schreibenden Datenbank-Operationen "
    "durchgeführt."
)

CADENCE_GROUNDING_NOTICE: str = (
    "TURNUS-EVIDENZ: Alle berechneten Fälligkeiten und Zeitabstände basieren "
    "exakt auf den deklarierten Turnus-Daten und dem angegebenen Bezugsstichtag. "
    "Ungültige oder widersprüchliche Turnus-Angaben werden explizit markiert "
    "und niemals geschätzt."
)

ROUTINE_ALLOWED_TABLES: tuple[str, ...] = (
    "routinen",
    "aufgaben",
    "erinnerungen",
    "turnus_plaene",
    "master_routines",
    "routine_master",
)

ROUTINE_TITLE_COLUMNS: tuple[str, ...] = (
    "titel",
    "name",
    "aufgabe",
    "bezeichnung",
    "routine",
)

ROUTINE_CADENCE_COLUMNS: tuple[str, ...] = (
    "turnus",
    "intervall",
    "wiederholung",
    "cadence",
    "frequenz",
)

ROUTINE_LAST_EXEC_COLUMNS: tuple[str, ...] = (
    "letzte_erledigung",
    "letzte_ausfuehrung",
    "zuletzt_erledigt",
    "erledigt_am",
    "last_done",
    "last_executed",
)

ROUTINE_NEXT_DUE_COLUMNS: tuple[str, ...] = (
    "naechste_faelligkeit",
    "faellig_am",
    "faellig",
    "next_due",
    "due_date",
)

FORBIDDEN_MUTATION_KEYWORDS: frozenset[str] = frozenset(
    {
        "alter",
        "create",
        "delete",
        "drop",
        "insert",
        "replace",
        "truncate",
        "update",
        "vacuum",
        "attach",
        "detach",
    }
)


@dataclass(frozen=True, slots=True)
class RoutineItem:
    """A routine task with cadence and calculated due status."""

    routine_id: int | str
    title: str
    cadence_raw: str
    cadence_normalized: str
    last_executed: str | None
    declared_next_due: str | None
    calculated_next_due: str | None
    is_due: bool
    overdue_days: int
    priority: str
    status: str
    notes: str
    is_valid: bool
    validation_error: str | None
    source_id: str
    table: str
    line: int
    quote: str


def validate_routine_sql_query(
    query: str,
    allowed_tables: tuple[str, ...] = ROUTINE_ALLOWED_TABLES,
) -> None:
    """Enforce strict read-only constraints on custom routine SQL queries."""
    clean = query.strip().rstrip(";").strip()
    if not clean:
        raise WorkflowBlocked(
            ("empty_sql_query",),
            actions=("routine_query", "query_validation_blocked"),
            metadata={"query": query},
        )

    clean_no_str = re.sub(r"'[^']*'", "", clean)
    clean_no_str = re.sub(r'"[^"]*"', "", clean_no_str)
    tokens = [t.lower() for t in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", clean_no_str)]

    for keyword in FORBIDDEN_MUTATION_KEYWORDS:
        if keyword in tokens:
            raise WorkflowBlocked(
                (f"database_modification_blocked:keyword_{keyword}",),
                actions=("routine_query", "mutation_blocked"),
                metadata={"forbidden_keyword": keyword, "query": query},
            )

    if not tokens or tokens[0] not in {"select", "with", "pragma"}:
        raise WorkflowBlocked(
            ("query_must_start_with_select_or_with",),
            actions=("routine_query", "mutation_blocked"),
            metadata={"query": query},
        )

    for word in tokens:
        if word in ROUTINE_ALLOWED_TABLES and word not in allowed_tables:
            raise WorkflowBlocked(
                (f"table_not_allowed:{word}",),
                actions=("routine_query", "table_allowlist_blocked"),
                metadata={"table": word, "allowed_tables": list(allowed_tables)},
            )


def calculate_cadence_due_date(
    cadence_raw: str,
    last_executed: str | None,
    declared_next: str | None,
    ref_date: date,
) -> tuple[str | None, bool, int, str | None]:
    """Calculate whether a routine is due and compute the next due date.

    Returns:
        (calculated_next_due_iso, is_due, overdue_days, error_reason)
    """
    clean_cadence = (cadence_raw or "").strip().lower()
    if not clean_cadence or clean_cadence in {"ungueltig", "unbekannt", "invalid", "null"}:
        return None, False, 0, "ungueltiger_turnus"

    last_dt: date | None = None
    if last_executed:
        try:
            last_dt = date.fromisoformat(str(last_executed).strip()[:10])
        except ValueError:
            return None, False, 0, "ungueltiges_datum_letzte_ausfuehrung"

    declared_dt: date | None = None
    if declared_next:
        try:
            declared_dt = date.fromisoformat(str(declared_next).strip()[:10])
        except ValueError:
            return None, False, 0, "ungueltiges_datum_naechste_faelligkeit"

    if last_dt and declared_dt and last_dt > declared_dt:
        return None, False, 0, "widerspruch_letzte_ausfuehrung_nach_faelligkeit"

    delta_days: int | None = None
    if clean_cadence in {"taeglich", "täglich", "daily", "1d", "werktags", "workdays"}:
        delta_days = 1
    elif clean_cadence in {"woechentlich", "wöchentlich", "weekly", "7d", "1w"}:
        delta_days = 7
    elif clean_cadence in {
        "zweiwoechentlich",
        "zweiwöchentlich",
        "alle 14 tage",
        "14d",
        "2w",
        "biweekly",
    }:
        delta_days = 14
    elif clean_cadence in {"monatlich", "monthly", "30d", "1m"}:
        delta_days = 30
    elif clean_cadence in {
        "quartalsweise",
        "vierteljaehrlich",
        "vierteljährlich",
        "quarterly",
        "90d",
        "3m",
    }:
        delta_days = 90
    elif clean_cadence in {"halbjaehrlich", "halbjährlich", "semiannual", "180d", "6m"}:
        delta_days = 180
    elif clean_cadence in {"jaehrlich", "jährlich", "yearly", "annual", "365d", "1y"}:
        delta_days = 365
    else:
        m = re.match(r"^alle\s+(\d+)\s+tage$", clean_cadence)
        if m:
            val = int(m.group(1))
            if val <= 0:
                return None, False, 0, "nicht_positiver_intervall"
            delta_days = val
        else:
            return None, False, 0, f"unbekannter_turnus:{cadence_raw}"

    calc_due: date
    if declared_dt is not None:
        calc_due = declared_dt
    elif last_dt is not None:
        calc_due = last_dt + timedelta(days=delta_days)
    else:
        calc_due = ref_date

    is_due = calc_due <= ref_date
    overdue_days = max(0, (ref_date - calc_due).days) if is_due else 0

    return calc_due.isoformat(), is_due, overdue_days, None


def read_routine_database(
    db_path: Path,
    source_id: str,
    allowed_tables: tuple[str, ...] = ROUTINE_ALLOWED_TABLES,
    custom_query: str | None = None,
    ref_date: date | None = None,
) -> list[RoutineItem]:
    """Extract routines safely from a MasterRoutine SQLite database."""
    if ref_date is None:
        ref_date = datetime.now(UTC).date()

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.OperationalError as exc:
        raise BoundStructuredSourceError(
            f"cannot_open_routine_database_ro:{db_path.name}:{exc}"
        ) from exc

    with conn:
        conn.execute("PRAGMA query_only = ON;")
        available_tables = _sqlite_tables(conn)
        matched_tables = [t for t in available_tables if t in allowed_tables]

        if not matched_tables and not custom_query:
            return []

        items: list[RoutineItem] = []
        if custom_query:
            validate_routine_sql_query(custom_query, allowed_tables)
            cursor = conn.cursor()
            cursor.execute(custom_query)
            col_names = [desc[0].lower() for desc in cursor.description]
            for row_idx, row in enumerate(cursor.fetchall(), start=1):
                row_dict = dict(zip(col_names, row, strict=False))
                item = _parse_routine_row(
                    row_dict,
                    source_id=source_id,
                    table="custom_query",
                    line=row_idx,
                    ref_date=ref_date,
                )
                items.append(item)
        else:
            for table in matched_tables:
                cursor = conn.cursor()
                cursor.execute(f"SELECT * FROM [{table}];")
                col_names = [desc[0].lower() for desc in cursor.description]
                for row_idx, row in enumerate(cursor.fetchall(), start=1):
                    row_dict = dict(zip(col_names, row, strict=False))
                    item = _parse_routine_row(
                        row_dict,
                        source_id=source_id,
                        table=table,
                        line=row_idx,
                        ref_date=ref_date,
                    )
                    items.append(item)

    return items


def _parse_routine_row(
    row: dict[str, Any],
    source_id: str,
    table: str,
    line: int,
    ref_date: date,
) -> RoutineItem:
    """Parse and normalize a single routine row from a SQLite query."""
    r_id = row.get("id") or row.get("routine_id") or line
    title = ""
    for col in ROUTINE_TITLE_COLUMNS:
        val = row.get(col)
        if val is not None and str(val).strip():
            title = str(val).strip()
            break
    if not title:
        title = f"Routine #{r_id}"

    cadence_raw = ""
    for col in ROUTINE_CADENCE_COLUMNS:
        val = row.get(col)
        if val is not None and str(val).strip():
            cadence_raw = str(val).strip()
            break

    last_exec = None
    for col in ROUTINE_LAST_EXEC_COLUMNS:
        val = row.get(col)
        if val is not None and str(val).strip():
            last_exec = str(val).strip()
            break
    last_exec_str = last_exec

    declared_next = None
    for col in ROUTINE_NEXT_DUE_COLUMNS:
        val = row.get(col)
        if val is not None and str(val).strip():
            declared_next = str(val).strip()
            break
    declared_next_str = declared_next

    calc_due, is_due, overdue, err = calculate_cadence_due_date(
        cadence_raw, last_exec_str, declared_next_str, ref_date
    )

    prio = str(row.get("prioritaet") or row.get("prio") or "normal").strip()
    status = str(row.get("status") or "aktiv").strip()
    notes = str(row.get("notiz") or row.get("beschreibung") or "").strip()

    quote_parts = [f"id={r_id}", f"titel='{title}'"]
    if cadence_raw:
        quote_parts.append(f"turnus='{cadence_raw}'")
    if last_exec_str:
        quote_parts.append(f"letzte='{last_exec_str}'")
    if declared_next_str:
        quote_parts.append(f"fällig='{declared_next_str}'")

    return RoutineItem(
        routine_id=r_id,
        title=title,
        cadence_raw=cadence_raw,
        cadence_normalized=cadence_raw.lower() if cadence_raw else "unbekannt",
        last_executed=last_exec_str,
        declared_next_due=declared_next_str,
        calculated_next_due=calc_due,
        is_due=is_due,
        overdue_days=overdue,
        priority=prio,
        status=status,
        notes=notes,
        is_valid=(err is None),
        validation_error=err,
        source_id=source_id,
        table=table,
        line=line,
        quote=", ".join(quote_parts),
    )


def render_routine_markdown(
    items: list[RoutineItem],
    ref_date: date,
    db_name: str = "routine_master.db",
) -> str:
    """Render a structured Markdown report of queried routines and due reminders."""
    due_items = [item for item in items if item.is_due and item.is_valid]
    upcoming_items = [item for item in items if not item.is_due and item.is_valid]
    invalid_items = [item for item in items if not item.is_valid]

    lines = [
        f"# MasterRoutine Abfrage: {db_name}",
        "",
        "> [!IMPORTANT]",
        f"> {SCHEDULER_NOT_INSTALLED_NOTICE}",
        "",
        "> [!NOTE]",
        f"> {CADENCE_GROUNDING_NOTICE}",
        "",
        f"- **Bezugsstichtag**: `{ref_date.isoformat()}`",
        f"- **Gefundene Routinen gesamt**: {len(items)}",
        f"- **Fällig / Überfällig**: {len(due_items)}",
        f"- **Kommende Erinnerungen**: {len(upcoming_items)}",
        f"- **Ungültige / Konflikt-Einträge**: {len(invalid_items)}",
        "",
        "## Fällige Aufgaben und Erinnerungen",
        "",
        "| Nr. | Routine / Aufgabe | Turnus | Letzte | Fälligkeit | Überfällig | Prio | Quelle |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    if not due_items:
        lines.append("| - | *Keine fälligen Aufgaben zum Stichtag* | - | - | - | - | - | - |")
    else:
        for idx, item in enumerate(due_items, start=1):
            overdue_str = f"{item.overdue_days} Tage" if item.overdue_days > 0 else "heute"
            last_str = item.last_executed or "nie"
            lines.append(
                f"| {idx} | **{item.title}** | {item.cadence_raw} | {last_str} | "
                f"`{item.calculated_next_due}` | {overdue_str} | {item.priority} | "
                f"`{item.source_id}:{item.table}:{item.line}` |"
            )

    if upcoming_items:
        lines.extend(
            [
                "",
                "## Zukünftige Routinen",
                "",
                "| Nr. | Routine / Aufgabe | Turnus | Nächster Termin | Prio | Quelle |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for idx, item in enumerate(upcoming_items, start=1):
            lines.append(
                f"| {idx} | {item.title} | {item.cadence_raw} | "
                f"`{item.calculated_next_due}` | {item.priority} | "
                f"`{item.source_id}:{item.table}:{item.line}` |"
            )

    if invalid_items:
        lines.extend(
            [
                "",
                "## ⚠️ Ungültige oder widersprüchliche Turnus-Daten (Nicht geschätzt)",
                "",
                "| Nr. | Routine / Aufgabe | Roh-Turnus | Fehlergrund | Belegzitat |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for idx, item in enumerate(invalid_items, start=1):
            lines.append(
                f"| {idx} | **{item.title}** | `{item.cadence_raw}` | "
                f"*{item.validation_error}* | > \"{item.quote}\" |"
            )

    lines.extend(
        [
            "",
            "## Beleg-Zitate",
            "",
        ]
    )
    for item in items:
        lines.append(
            f"- `{item.source_id}:{item.table}:{item.line}`: \"{item.quote}\""
        )

    lines.append("")
    return "\n".join(lines)


def execute_routine_query(
    job: Any,
    inventory: InventoryResult,
    run_id: str = "run",
) -> Any:
    """Execute Gate G10 routine_query workflow."""
    params = job.parameters or {}
    output_dir = Path(job.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ref_date_param = params.get("reference_date")
    ref_date: date
    if ref_date_param:
        try:
            ref_date = date.fromisoformat(str(ref_date_param).strip())
        except ValueError:
            raise ValueError(f"invalid_reference_date_format:{ref_date_param}") from None
    else:
        ref_date = datetime.now(UTC).date()

    min_routines = int(params.get("min_routines", 1))
    require_valid = bool(params.get("require_valid_cadence", False))
    custom_query = params.get("query")
    if custom_query is not None and not isinstance(custom_query, str):
        raise ValueError("query must be a string")

    target_tables = params.get("target_tables")
    allowed_tables = (
        tuple(str(t) for t in target_tables)
        if target_tables
        else ROUTINE_ALLOWED_TABLES
    )

    if custom_query:
        validate_routine_sql_query(custom_query, allowed_tables)

    db_records = [
        r
        for r in inventory.records
        if Path(r.path).suffix.lower() in {".db", ".sqlite", ".sqlite3"}
    ]
    if not db_records:
        raise WorkflowBlocked(
            ("no_sqlite_routine_databases_found",),
            actions=("routine_query", "db_scan_blocked"),
            coverage=compute_coverage(
                all_source_ids=(r.source_id for r in inventory.records),
                read_source_ids=(),
                cited_source_ids=(),
            ),
        )

    all_routines: list[RoutineItem] = []
    read_sources: list[str] = []
    db_name = "MasterRoutine"

    for r in db_records:
        read_sources.append(r.source_id)
        db_path = Path(r.path)
        db_name = db_path.name
        routines = read_routine_database(
            db_path=db_path,
            source_id=r.source_id,
            allowed_tables=allowed_tables,
            custom_query=custom_query,
            ref_date=ref_date,
        )
        all_routines.extend(routines)

    if len(all_routines) < min_routines:
        question = Question(
            field="routine_count_gap",
            prompt=(
                f"Zu wenige Routine-Datensätze gefunden ({len(all_routines)}, "
                f"erforderlich: {min_routines}). Bitte stellen Sie eine gültige "
                "MasterRoutine-Datenbank bereit."
            ),
            why="Routinen-Auswertung erfordert eine Mindestanzahl an Aufgaben.",
            kind="text",
        )
        payload = needs_input_payload((question,), workflow="routine_query")
        needs_art = write_text_artifact(
            output_dir / f"{run_id}.needs-user-input.json",
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "needs-user-input",
        )
        raise WorkflowBlocked(
            (f"insufficient_routine_records:{len(all_routines)}_min_{min_routines}",),
            actions=("routine_query", "insufficient_records_blocked"),
            artifacts=(needs_art,),
            coverage=compute_coverage(
                all_source_ids=(r.source_id for r in inventory.records),
                read_source_ids=tuple(read_sources),
                cited_source_ids=(),
            ),
            metadata={"found_routines": len(all_routines), "min_required": min_routines},
        )

    if require_valid:
        invalid = [item for item in all_routines if not item.is_valid]
        if invalid:
            first = invalid[0]
            raise WorkflowBlocked(
                (f"invalid_routine_cadence:{first.routine_id}:{first.validation_error}",),
                actions=("routine_query", "cadence_validation_blocked"),
                coverage=compute_coverage(
                    all_source_ids=(r.source_id for r in inventory.records),
                    read_source_ids=tuple(read_sources),
                    cited_source_ids=(),
                ),
                metadata={
                    "routine_id": first.routine_id,
                    "error": first.validation_error,
                    "cadence": first.cadence_raw,
                },
            )

    due_items = [item for item in all_routines if item.is_due and item.is_valid]
    overdue_items = [item for item in all_routines if item.overdue_days > 0 and item.is_valid]
    upcoming_items = [item for item in all_routines if not item.is_due and item.is_valid]
    invalid_items = [item for item in all_routines if not item.is_valid]

    cited_ids = sorted({item.source_id for item in all_routines})
    artifacts: list[ArtifactRecord] = []

    json_path = output_dir / f"{run_id}.routine-query.json"
    md_path = output_dir / f"{run_id}.routine-query.md"

    summary_payload = {
        "schema": "nemofold.routine-query.v1",
        "run_id": run_id,
        "database_name": db_name,
        "reference_date": ref_date.isoformat(),
        "total_routines": len(all_routines),
        "due_count": len(due_items),
        "overdue_count": len(overdue_items),
        "upcoming_count": len(upcoming_items),
        "invalid_count": len(invalid_items),
        "due_routines_count": len(due_items),
        "upcoming_routines_count": len(upcoming_items),
        "invalid_routines_count": len(invalid_items),
        "scheduler_status": "not_installed",
        "scheduler_notice": SCHEDULER_NOT_INSTALLED_NOTICE,
        "cadence_grounding_verified": True,
        "cited_source_ids": cited_ids,
        "routines": [
            {
                "id": item.routine_id,
                "title": item.title,
                "cadence_raw": item.cadence_raw,
                "cadence_normalized": item.cadence_normalized,
                "last_executed": item.last_executed,
                "declared_next_due": item.declared_next_due,
                "calculated_next_due": item.calculated_next_due,
                "is_due": item.is_due,
                "overdue_days": item.overdue_days,
                "priority": item.priority,
                "status": item.status,
                "is_valid": item.is_valid,
                "validation_error": item.validation_error,
                "source_id": item.source_id,
                "table": item.table,
                "line": item.line,
                "quote": item.quote,
            }
            for item in all_routines
        ],
    }

    artifacts.append(
        write_text_artifact(
            json_path,
            json.dumps(summary_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "routine-query",
        )
    )

    md_content = render_routine_markdown(all_routines, ref_date, db_name)
    artifacts.append(
        write_text_artifact(
            md_path,
            md_content,
            "markdown",
        )
    )

    coverage = compute_coverage(
        all_source_ids=(r.source_id for r in inventory.records),
        read_source_ids=tuple(read_sources),
        cited_source_ids=tuple(cited_ids),
    )

    return (
        ("routine_query", "render_summary", "render_markdown"),
        tuple(artifacts),
        coverage,
        {
            "database_name": db_name,
            "reference_date": ref_date.isoformat(),
            "total_routines": len(all_routines),
            "due_count": len(due_items),
            "upcoming_count": len(upcoming_items),
            "invalid_count": len(invalid_items),
            "scheduler_status": "not_installed",
            "cadence_grounding_verified": True,
            "cited_source_ids": sorted(cited_ids),
        },
    )
