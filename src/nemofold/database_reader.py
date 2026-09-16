"""Executable database reader for Gate G08: Safe Specialist Database Access (Ellmos UC 42, 45).

Provides strict read-only access to specialist local SQLite databases such as
HausLagerist (inventory/locations) and MediPlaner (prescriptions/schedules) under
schema allowlists, mutation protection, and fail-closed validation.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .application import WorkflowBlocked
from .artifacts import write_text_artifact
from .completeness import Question, needs_input_payload
from .contracts import ArtifactRecord, Coverage
from .inventory import InventoryResult
from .structured_sources import (
    _IDENTIFIER,
    BoundStructuredSourceError,
    StructuredSourceError,
    _sqlite_tables,
)

HAUSLAGERIST_ALLOWED_TABLES: tuple[str, ...] = (
    "gegenstaende",
    "inventar",
    "lagerorte",
    "kategorien",
)
HAUSLAGERIST_REQUIRED_ITEM_COLUMNS: tuple[str, ...] = ("lagerort",)
HAUSLAGERIST_ITEM_NAME_CANDIDATES: tuple[str, ...] = (
    "gegenstand",
    "name",
    "titel",
    "artikel",
    "bezeichnung",
)

MEDIPLANER_ALLOWED_TABLES: tuple[str, ...] = (
    "rezepte",
    "medikamente",
    "einnahmeplaene",
    "dosierungen",
    "notizen",
)
MEDIPLANER_REQUIRED_RECIPE_COLUMNS: tuple[str, ...] = ("dosis",)
MEDIPLANER_RECIPE_NAME_CANDIDATES: tuple[str, ...] = (
    "praeparat",
    "name",
    "medikament",
    "arzneimittel",
)

FORBIDDEN_MUTATION_KEYWORDS: frozenset[str] = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE",
        "REPLACE",
        "ATTACH",
        "DETACH",
        "VACUUM",
        "REINDEX",
        "PRAGMA",
        "TRANSACTION",
        "COMMIT",
        "ROLLBACK",
        "EXEC",
        "EXECUTE",
        "GRANT",
        "REVOKE",
    }
)

FORBIDDEN_TABLE_KEYWORDS: frozenset[str] = frozenset(
    {
        "passwoerter",
        "passwords",
        "secrets",
        "system_config",
        "credentials",
        "users_private",
        "sqlite_master",
        "sqlite_temp_master",
        "admin",
    }
)

READ_ONLY_AUDIT_NOTICE: str = (
    "*Sicherheitsnachweis: Datenbank wurde strikt im Read-Only-Modus "
    "(mode=ro, PRAGMA query_only=ON) abgefragt. Keine Schreiboperationen zulässig.*"
)


class DatabaseReaderError(RuntimeError):
    """Raised when specialist database reading fails its validation contract."""


@dataclass(frozen=True, slots=True)
class InventoryItem:
    """An inventory record extracted from a HausLagerist database."""

    gegenstand: str
    lagerort: str
    menge: str
    kategorie: str
    zustand: str
    notiz: str
    source_id: str
    table_name: str
    row_number: int


@dataclass(frozen=True, slots=True)
class MedicationPlanItem:
    """A medication plan record extracted from a MediPlaner database."""

    praeparat: str
    wirkstoff: str
    dosis: str
    einnahmezeit: str
    arzt: str
    ausgestellt: str
    notiz: str
    source_id: str
    table_name: str
    row_number: int


@dataclass(frozen=True, slots=True)
class GenericDatabaseRecord:
    """A record extracted from a generic allowed SQLite table."""

    table_name: str
    record_id: str
    fields: dict[str, str]
    source_id: str
    row_number: int


@dataclass(frozen=True, slots=True)
class DatabaseReaderSummary:
    """Complete summary of the safe database extraction."""

    database_profile: str
    database_file: str
    database_sha256: str
    tables_read: tuple[str, ...]
    total_records: int
    read_only_verified: bool
    inventory_items: tuple[InventoryItem, ...] = ()
    medication_items: tuple[MedicationPlanItem, ...] = ()
    generic_records: tuple[GenericDatabaseRecord, ...] = ()
    notes: tuple[str, ...] = ()


def validate_sql_query(query: str, allowed_tables: tuple[str, ...]) -> None:
    """Ensure a custom query is strictly read-only and targets allowed tables only."""
    stripped = query.strip()
    if not stripped:
        raise ValueError("empty_query_not_allowed")

    statements = [stmt.strip() for stmt in stripped.split(";") if stmt.strip()]
    if len(statements) > 1:
        raise WorkflowBlocked(
            ("database_modification_blocked:multiple_statements_forbidden",),
            actions=("database_query_evaluated", "multiple_statements_blocked"),
            metadata={"query": query},
        )

    single_stmt = statements[0]
    first_word = single_stmt.split()[0].upper()
    if first_word not in {"SELECT", "WITH"}:
        raise WorkflowBlocked(
            (f"database_modification_blocked:non_select_statement:{first_word}",),
            actions=("database_query_evaluated", "mutation_attempt_blocked"),
            metadata={"statement": single_stmt, "first_word": first_word},
        )

    tokens = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", single_stmt))
    upper_tokens = {tok.upper() for tok in tokens}

    for forbidden in FORBIDDEN_MUTATION_KEYWORDS:
        if forbidden in upper_tokens:
            raise WorkflowBlocked(
                (f"database_modification_blocked:{forbidden}",),
                actions=("database_query_evaluated", "mutation_attempt_blocked"),
                metadata={"statement": single_stmt, "forbidden_keyword": forbidden},
            )

    for forbidden_tbl in FORBIDDEN_TABLE_KEYWORDS:
        if any(tok.casefold() == forbidden_tbl.casefold() for tok in tokens):
            raise WorkflowBlocked(
                (f"table_not_allowed:{forbidden_tbl}",),
                actions=("schema_validation", "forbidden_table_blocked"),
                metadata={"statement": single_stmt, "forbidden_table": forbidden_tbl},
            )


def detect_database_profile(
    filename: str,
    tables: tuple[str, ...],
    requested_profile: str | None = None,
) -> str:
    """Infer the database profile (hauslagerist, mediplaner, generic)."""
    if requested_profile in {"hauslagerist", "mediplaner", "generic"}:
        return requested_profile

    lower_name = filename.casefold()
    lower_tables = {t.casefold() for t in tables}

    if "hauslagerist" in lower_name or "inventar" in lower_name:
        return "hauslagerist"
    if any(t in lower_tables for t in ("gegenstaende", "lagerorte", "kategorien")):
        return "hauslagerist"

    if "mediplaner" in lower_name or "rezept" in lower_name:
        return "mediplaner"
    if any(t in lower_tables for t in ("rezepte", "einnahmeplaene", "dosierungen")):
        return "mediplaner"

    return "generic"


def _read_table_columns(connection: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    cursor = connection.execute(f'PRAGMA table_info("{table_name}")')
    return tuple(str(row[1]) for row in cursor.fetchall())


def _resolve_column(columns: tuple[str, ...], candidates: tuple[str, ...]) -> str | None:
    lookup = {col.casefold(): col for col in columns}
    for cand in candidates:
        if cand.casefold() in lookup:
            return lookup[cand.casefold()]
    return None


def _extract_hauslagerist(
    connection: sqlite3.Connection,
    table_name: str,
    source_id: str,
) -> tuple[tuple[InventoryItem, ...], tuple[str, ...]]:
    columns = _read_table_columns(connection, table_name)
    name_col = _resolve_column(columns, HAUSLAGERIST_ITEM_NAME_CANDIDATES)
    lagerort_col = _resolve_column(columns, HAUSLAGERIST_REQUIRED_ITEM_COLUMNS)

    if not name_col:
        raise WorkflowBlocked(
            (f"missing_schema_columns:{table_name}:gegenstand",),
            actions=("schema_validation", "missing_columns_blocked"),
            metadata={"table": table_name, "required": "gegenstand/name"},
        )
    if not lagerort_col:
        raise WorkflowBlocked(
            (f"missing_schema_columns:{table_name}:lagerort",),
            actions=("schema_validation", "missing_columns_blocked"),
            metadata={"table": table_name, "required": "lagerort"},
        )

    menge_col = _resolve_column(columns, ("menge", "anzahl", "stueck"))
    kat_col = _resolve_column(columns, ("kategorie", "rubrik", "typ"))
    zustand_col = _resolve_column(columns, ("zustand", "status"))
    notiz_col = _resolve_column(columns, ("notiz", "notizen", "beschreibung", "bemerkung"))

    cursor = connection.execute(f'SELECT * FROM "{table_name}" ORDER BY 1')
    rows = cursor.fetchall()
    col_index = {col: idx for idx, col in enumerate(columns)}

    items: list[InventoryItem] = []
    for row_num, row in enumerate(rows, start=1):
        name_val = str(row[col_index[name_col]] or "").strip()
        ort_val = str(row[col_index[lagerort_col]] or "").strip()
        menge_val = str(row[col_index[menge_col]] or "1").strip() if menge_col else "1"
        kat_val = str(row[col_index[kat_col]] or "-").strip() if kat_col else "-"
        zustand_val = str(row[col_index[zustand_col]] or "-").strip() if zustand_col else "-"
        notiz_val = str(row[col_index[notiz_col]] or "").strip() if notiz_col else ""

        items.append(
            InventoryItem(
                gegenstand=name_val,
                lagerort=ort_val,
                menge=menge_val,
                kategorie=kat_val,
                zustand=zustand_val,
                notiz=notiz_val,
                source_id=source_id,
                table_name=table_name,
                row_number=row_num,
            )
        )
    return tuple(items), (f"Extracted {len(items)} inventory item(s) from table '{table_name}'.",)


def _extract_mediplaner(
    connection: sqlite3.Connection,
    table_name: str,
    source_id: str,
) -> tuple[tuple[MedicationPlanItem, ...], tuple[str, ...]]:
    columns = _read_table_columns(connection, table_name)
    name_col = _resolve_column(columns, MEDIPLANER_RECIPE_NAME_CANDIDATES)
    dosis_col = _resolve_column(columns, MEDIPLANER_REQUIRED_RECIPE_COLUMNS)

    if not name_col:
        raise WorkflowBlocked(
            (f"missing_schema_columns:{table_name}:praeparat",),
            actions=("schema_validation", "missing_columns_blocked"),
            metadata={"table": table_name, "required": "praeparat/name"},
        )
    if not dosis_col:
        raise WorkflowBlocked(
            (f"missing_schema_columns:{table_name}:dosis",),
            actions=("schema_validation", "missing_columns_blocked"),
            metadata={"table": table_name, "required": "dosis"},
        )

    wirkstoff_col = _resolve_column(columns, ("wirkstoff", "substanz"))
    schema_col = _resolve_column(columns, ("einnahmezeit", "schema", "einnahme", "zeit"))
    arzt_col = _resolve_column(columns, ("arzt", "verordner", "doktor"))
    datum_col = _resolve_column(columns, ("ausgestellt", "datum", "verordnet_am"))
    notiz_col = _resolve_column(columns, ("notiz", "notizen", "hinweis"))

    cursor = connection.execute(f'SELECT * FROM "{table_name}" ORDER BY 1')
    rows = cursor.fetchall()
    col_index = {col: idx for idx, col in enumerate(columns)}

    items: list[MedicationPlanItem] = []
    for row_num, row in enumerate(rows, start=1):
        name_val = str(row[col_index[name_col]] or "").strip()
        dosis_val = str(row[col_index[dosis_col]] or "").strip()
        wirk_val = str(row[col_index[wirkstoff_col]] or "-").strip() if wirkstoff_col else "-"
        schema_val = str(row[col_index[schema_col]] or "-").strip() if schema_col else "-"
        arzt_val = str(row[col_index[arzt_col]] or "-").strip() if arzt_col else "-"
        datum_val = str(row[col_index[datum_col]] or "-").strip() if datum_col else "-"
        notiz_val = str(row[col_index[notiz_col]] or "").strip() if notiz_col else ""

        items.append(
            MedicationPlanItem(
                praeparat=name_val,
                wirkstoff=wirk_val,
                dosis=dosis_val,
                einnahmezeit=schema_val,
                arzt=arzt_val,
                ausgestellt=datum_val,
                notiz=notiz_val,
                source_id=source_id,
                table_name=table_name,
                row_number=row_num,
            )
        )
    return tuple(items), (f"Extracted {len(items)} recipe record(s) from table '{table_name}'.",)


def _extract_generic(
    connection: sqlite3.Connection,
    table_name: str,
    source_id: str,
) -> tuple[tuple[GenericDatabaseRecord, ...], tuple[str, ...]]:
    columns = _read_table_columns(connection, table_name)
    cursor = connection.execute(f'SELECT * FROM "{table_name}" ORDER BY 1')
    rows = cursor.fetchall()

    records: list[GenericDatabaseRecord] = []
    for row_num, row in enumerate(rows, start=1):
        fields = {
            col: str(val if val is not None else "")
            for col, val in zip(columns, row, strict=False)
        }
        rec_id = str(row[0] if row else row_num)
        records.append(
            GenericDatabaseRecord(
                table_name=table_name,
                record_id=rec_id,
                fields=fields,
                source_id=source_id,
                row_number=row_num,
            )
        )
    return tuple(records), (f"Extracted {len(records)} record(s) from table '{table_name}'.",)


def read_specialist_database(
    db_path: str | Path,
    *,
    source_id: str,
    source_sha256: str,
    requested_profile: str | None = None,
    allowed_tables_param: tuple[str, ...] = (),
    forbidden_tables_param: tuple[str, ...] = (),
    target_tables_param: tuple[str, ...] = (),
    custom_query: str | None = None,
) -> DatabaseReaderSummary:
    """Open and safely read the database under strict read-only and allowlist rules."""
    path = Path(db_path).resolve()
    if not path.is_file():
        raise WorkflowBlocked(
            ("schema_validation_failed:file_not_found",),
            actions=("database_access", "file_not_found_blocked"),
            metadata={"path": str(path)},
        )

    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise WorkflowBlocked(
            (f"schema_validation_failed:{exc}",),
            actions=("database_access", "connect_failed_blocked"),
            metadata={"path": str(path), "error": str(exc)},
        ) from exc

    try:
        connection.execute("PRAGMA query_only=ON")
        available_tables = _sqlite_tables(connection)
    except (sqlite3.Error, StructuredSourceError, BoundStructuredSourceError) as exc:
        connection.close()
        raise WorkflowBlocked(
            (f"schema_validation_failed:{exc}",),
            actions=("database_access", "query_only_failed_blocked"),
            metadata={"path": str(path), "error": str(exc)},
        ) from exc

    profile = detect_database_profile(path.name, available_tables, requested_profile)

    # Determine allowed tables
    if allowed_tables_param:
        allowed_tables = allowed_tables_param
    elif profile == "hauslagerist":
        allowed_tables = HAUSLAGERIST_ALLOWED_TABLES
    elif profile == "mediplaner":
        allowed_tables = MEDIPLANER_ALLOWED_TABLES
    else:
        allowed_tables = available_tables

    all_forbidden = FORBIDDEN_TABLE_KEYWORDS | set(forbidden_tables_param)

    # Check custom query if provided
    if custom_query:
        validate_sql_query(custom_query, allowed_tables)

    # Check target tables
    target_tables = target_tables_param or tuple(
        t for t in available_tables if t in allowed_tables
    )

    # Fail closed on unauthorized or forbidden tables
    for tbl in target_tables:
        if tbl.casefold() in {f.casefold() for f in all_forbidden}:
            connection.close()
            raise WorkflowBlocked(
                (f"table_not_allowed:{tbl}",),
                actions=("schema_validation", "forbidden_table_blocked"),
                metadata={"table": tbl, "allowed_tables": list(allowed_tables)},
            )
        if tbl not in allowed_tables:
            connection.close()
            raise WorkflowBlocked(
                (f"table_not_allowed:{tbl}",),
                actions=("schema_validation", "unauthorized_table_blocked"),
                metadata={"table": tbl, "allowed_tables": list(allowed_tables)},
            )
        if tbl not in available_tables:
            connection.close()
            raise WorkflowBlocked(
                (f"missing_required_table:{tbl}",),
                actions=("schema_validation", "missing_table_blocked"),
                metadata={"table": tbl, "available_tables": list(available_tables)},
            )

    inv_items: list[InventoryItem] = []
    med_items: list[MedicationPlanItem] = []
    gen_records: list[GenericDatabaseRecord] = []
    notes: list[str] = []

    try:
        for tbl in target_tables:
            if not _IDENTIFIER.fullmatch(tbl):
                raise WorkflowBlocked(
                    (f"table_not_allowed:invalid_identifier:{tbl}",),
                    actions=("schema_validation", "invalid_identifier_blocked"),
                    metadata={"table": tbl},
                )
            if profile == "hauslagerist" and tbl in ("gegenstaende", "inventar"):
                extracted, n = _extract_hauslagerist(connection, tbl, source_id)
                inv_items.extend(extracted)
                notes.extend(n)
            elif profile == "mediplaner" and tbl in ("rezepte", "medikamente"):
                extracted, n = _extract_mediplaner(connection, tbl, source_id)
                med_items.extend(extracted)
                notes.extend(n)
            else:
                extracted, n = _extract_generic(connection, tbl, source_id)
                gen_records.extend(extracted)
                notes.extend(n)
    finally:
        connection.close()

    total_records = len(inv_items) + len(med_items) + len(gen_records)

    return DatabaseReaderSummary(
        database_profile=profile,
        database_file=path.name,
        database_sha256=source_sha256,
        tables_read=target_tables,
        total_records=total_records,
        read_only_verified=True,
        inventory_items=tuple(inv_items),
        medication_items=tuple(med_items),
        generic_records=tuple(gen_records),
        notes=tuple(notes),
    )


def render_database_markdown(summary: DatabaseReaderSummary, title: str | None = None) -> str:
    """Format safe specialist database extract as GitHub-flavored Markdown."""
    lines: list[str] = []

    if title:
        lines.append(f"# {title}")
    elif summary.database_profile == "hauslagerist":
        lines.append("# HausLagerist Inventar-Register")
    elif summary.database_profile == "mediplaner":
        lines.append("# MediPlaner Medikations- und Einnahmeplan")
    else:
        lines.append("# Fachdatenbank Auszug")
    lines.append("")

    lines.append(READ_ONLY_AUDIT_NOTICE)
    lines.append("")

    lines.append("## Übersicht")
    lines.append(f"- **Datenbank:** `{summary.database_file}`")
    lines.append(f"- **Profil:** `{summary.database_profile}`")
    lines.append(f"- **SHA-256:** `{summary.database_sha256}`")
    lines.append(f"- **Gelesene Tabellen:** {', '.join(summary.tables_read) or 'keine'}")
    lines.append(f"- **Datensätze gesamt:** {summary.total_records}")
    lines.append("- **Read-Only verifiziert:** Ja (`mode=ro`, `PRAGMA query_only=ON`)")
    lines.append("")

    if summary.inventory_items:
        lines.append("## Inventar & Lagerorte")
        lines.append("| Gegenstand | Lagerort | Menge | Kategorie | Zustand | Notiz |")
        lines.append("|---|---|---|---|---|---|")
        for item in summary.inventory_items:
            lines.append(
                f"| {item.gegenstand} | {item.lagerort} | {item.menge} | "
                f"{item.kategorie} | {item.zustand} | {item.notiz or '-'} |"
            )
        lines.append("")

    if summary.medication_items:
        lines.append("## Rezepte & Medikationsplan")
        lines.append("| Präparat | Wirkstoff | Dosis | Einnahmezeit | Arzt | Ausgestellt |")
        lines.append("|---|---|---|---|---|---|")
        for med in summary.medication_items:
            lines.append(
                f"| {med.praeparat} | {med.wirkstoff} | {med.dosis} | "
                f"{med.einnahmezeit} | {med.arzt} | {med.ausgestellt} |"
            )
        lines.append("")

    if summary.generic_records:
        lines.append("## Tabellendaten")
        for tbl in summary.tables_read:
            tbl_recs = [r for r in summary.generic_records if r.table_name == tbl]
            if not tbl_recs:
                continue
            cols = list(tbl_recs[0].fields.keys())
            lines.append(f"### Tabelle `{tbl}`")
            lines.append("| " + " | ".join(cols) + " |")
            lines.append("|" + "|".join("---" for _ in cols) + "|")
            for rec in tbl_recs:
                lines.append("| " + " | ".join(rec.fields.get(c, "-") for c in cols) + " |")
            lines.append("")

    lines.append("---")
    lines.append(
        f"*Status: {summary.total_records} Datensätze aus {len(summary.tables_read)} "
        "Tabelle(n) sicher im Read-Only-Modus extrahiert.*"
    )
    lines.append("")
    return "\n".join(lines)


def execute_database_reader(
    job: Any,
    inventory: InventoryResult,
    *,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, object]]:
    """Execute the database reader workflow under Gate G08 contracts."""
    db_suffixes = frozenset({".db", ".sqlite", ".sqlite3"})
    db_sources = [
        rec for rec in inventory.records
        if Path(rec.path).suffix.casefold() in db_suffixes
        and rec.extraction_status not in {"unreadable", "excluded_symlink"}
    ]

    output = Path(job.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    coverage = Coverage(
        total_sources=len(inventory.records),
        read_sources=len(db_sources),
        cited_sources=len(db_sources),
        unread_source_ids=tuple(
            rec.source_id for rec in inventory.records if rec not in db_sources
        ),
        uncited_read_source_ids=(),
    )

    if not db_sources:
        raise WorkflowBlocked(
            ("schema_validation_failed:no_sqlite_databases_found",),
            actions=("scan_inventory", "no_databases_blocked"),
            artifacts=(),
            coverage=coverage,
            metadata={"sources_scanned": len(inventory.records)},
        )

    # Take primary database source
    target_db = db_sources[0]

    req_profile = job.parameters.get("database_profile")
    allowed_param = tuple(job.parameters.get("allowed_tables") or ())
    forbidden_param = tuple(job.parameters.get("forbidden_tables") or ())
    target_param = tuple(job.parameters.get("target_tables") or ())
    query_param = job.parameters.get("query")
    min_records = int(job.parameters.get("min_records", 1))

    summary = read_specialist_database(
        target_db.path,
        source_id=target_db.source_id,
        source_sha256=target_db.sha256,
        requested_profile=req_profile,
        allowed_tables_param=allowed_param,
        forbidden_tables_param=forbidden_param,
        target_tables_param=target_param,
        custom_query=query_param,
    )

    # Floor check: min_records
    if summary.total_records < min_records:
        question = Question(
            field="database_records",
            prompt=(
                f"Zu wenige Datensätze in Datenbank '{summary.database_file}' gefunden "
                f"({summary.total_records} < {min_records}). Bitte stellen Sie eine Datenbank "
                "mit hinterlegten Datensätzen bereit."
            ),
            why="Das Datenbank-Gate verlangt mindestens die deklarierte Anzahl an Datensätzen.",
            kind="text",
        )
        asked = needs_input_payload((question,), workflow=job.workflow)
        needs_art = write_text_artifact(
            output / f"{run_id}.needs-user-input.json",
            json.dumps(asked, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "needs-user-input",
        )
        raise WorkflowBlocked(
            (f"insufficient_database_records:{summary.total_records}<{min_records}",),
            actions=("database_read_executed", "insufficient_records_blocked"),
            artifacts=(needs_art,),
            coverage=coverage,
            metadata={
                "total_records": summary.total_records,
                "target_min": min_records,
                "needs_user_input": True,
            },
        )

    # Write output artifacts
    json_payload = {
        "database_profile": summary.database_profile,
        "database_file": summary.database_file,
        "database_sha256": summary.database_sha256,
        "read_only_verified": summary.read_only_verified,
        "tables_read": list(summary.tables_read),
        "total_records": summary.total_records,
        "inventory_items": [
            {
                "gegenstand": item.gegenstand,
                "lagerort": item.lagerort,
                "menge": item.menge,
                "kategorie": item.kategorie,
                "zustand": item.zustand,
                "notiz": item.notiz,
                "source_id": item.source_id,
                "table": item.table_name,
                "row": item.row_number,
            }
            for item in summary.inventory_items
        ],
        "medication_items": [
            {
                "praeparat": med.praeparat,
                "wirkstoff": med.wirkstoff,
                "dosis": med.dosis,
                "einnahmezeit": med.einnahmezeit,
                "arzt": med.arzt,
                "ausgestellt": med.ausgestellt,
                "notiz": med.notiz,
                "source_id": med.source_id,
                "table": med.table_name,
                "row": med.row_number,
            }
            for med in summary.medication_items
        ],
        "generic_records": [
            {
                "table": rec.table_name,
                "id": rec.record_id,
                "fields": rec.fields,
                "source_id": rec.source_id,
                "row": rec.row_number,
            }
            for rec in summary.generic_records
        ],
        "boundary_note": "Ausschließlich autorisierte Tabellen im Read-Only-Modus ausgelesen.",
    }

    title_param = job.parameters.get("title")
    md_text = render_database_markdown(summary, title=title_param)

    json_art = write_text_artifact(
        output / f"{run_id}.database-reader.json",
        json.dumps(json_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "json",
    )
    md_art = write_text_artifact(
        output / f"{run_id}.database-reader.md",
        md_text,
        "markdown",
    )

    actions = (
        f"verified read-only database '{summary.database_file}'",
        f"read {summary.total_records} record(s) from table(s): {', '.join(summary.tables_read)}",
        f"rendered database report with {len(summary.tables_read)} table(s)",
    )

    metadata: dict[str, object] = {
        "database_file": summary.database_file,
        "database_profile": summary.database_profile,
        "database_sha256": summary.database_sha256,
        "tables_read": list(summary.tables_read),
        "total_records": summary.total_records,
        "read_only_verified": True,
        "inventory_count": len(summary.inventory_items),
        "medication_count": len(summary.medication_items),
        "generic_count": len(summary.generic_records),
    }

    return actions, (json_art, md_art), coverage, metadata
