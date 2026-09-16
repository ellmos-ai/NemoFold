"""Turn a folder of documents into a table with a source anchor in every cell.

This is the "text mass becomes data" core. It reads labelled values out of the
approved sources deterministically - no model, no inference - and records for
every filled cell which source and which line it came from. A cell it cannot
find stays empty on purpose: an invented value would defeat the entire product.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .primitives import FieldSpec, extract_fields

MAX_COLUMNS = 24
MAX_VALUE_CHARS = 300
MAX_ROWS = 500
LABEL_SEPARATORS = ":：–—-"


@dataclass(frozen=True, slots=True)
class RegistryColumn:
    name: str
    description: str = ""
    aliases: tuple[str, ...] = ()

    def spec(self) -> FieldSpec:
        return FieldSpec(name=self.name, description=self.description, aliases=self.aliases)

    def labels(self) -> tuple[str, ...]:
        return self.spec().labels()


@dataclass(frozen=True, slots=True)
class RegistryCell:
    column: str
    value: str | None = None
    source_id: str | None = None
    line: int | None = None
    quote: str | None = None

    @property
    def filled(self) -> bool:
        return self.value is not None


@dataclass(frozen=True, slots=True)
class RegistryRow:
    source_id: str
    display_name: str
    cells: tuple[RegistryCell, ...]
    record_line: int | None = None

    @property
    def filled_count(self) -> int:
        return sum(1 for cell in self.cells if cell.filled)


@dataclass(frozen=True, slots=True)
class RegistryTable:
    columns: tuple[RegistryColumn, ...]
    rows: tuple[RegistryRow, ...]
    skipped_source_ids: tuple[str, ...] = ()

    @property
    def filled_cells(self) -> int:
        return sum(row.filled_count for row in self.rows)

    @property
    def empty_cells(self) -> int:
        return len(self.rows) * len(self.columns) - self.filled_cells


# Column templates for the three leading cases. They are starting points a job
# can override; every label list carries the German and English wording people
# actually put in their documents.
COLUMN_TEMPLATES: dict[str, tuple[RegistryColumn, ...]] = {
    "medical_reports": (
        RegistryColumn("Name", "Patient or report subject",
                       ("Patient", "Patientin", "Patient name", "Betreff")),
        RegistryColumn("Fachrichtung", "Medical speciality",
                       ("Speciality", "Specialty", "Abteilung", "Department", "Fachgebiet")),
        RegistryColumn("Arzt", "Reporting physician",
                       ("Ärztin", "Arzt/Ärztin", "Physician", "Doctor", "Behandler")),
        RegistryColumn("Kontakt", "Practice contact",
                       ("Contact", "Telefon", "Phone", "E-Mail", "Email", "Praxis")),
        RegistryColumn("Befund", "Finding or diagnosis",
                       ("Finding", "Diagnose", "Diagnosis", "Ergebnis")),
    ),
    "insurance_registry": (
        RegistryColumn("Police", "Policy number",
                       ("Policy", "Policennummer", "Versicherungsschein", "Vertragsnummer")),
        RegistryColumn("Tarif", "Tariff or plan",
                       ("Tariff", "Plan", "Produkt", "Product")),
        RegistryColumn("Abdeckung", "What the policy covers",
                       ("Coverage", "Deckung", "Leistung", "Umfang")),
        RegistryColumn("Kosten", "Premium or cost",
                       ("Cost", "Beitrag", "Prämie", "Premium", "Preis")),
        RegistryColumn("Kontakt", "Insurer contact",
                       ("Contact", "Telefon", "Phone", "E-Mail", "Email", "Berater")),
    ),
    "recurring_costs": (
        RegistryColumn("Vertrag", "Contract or subscription",
                       ("Contract", "Vertragsgegenstand", "Subscription", "Abo", "Leistung")),
        RegistryColumn("Betrag", "Amount per period",
                       ("Amount", "Kosten", "Cost", "Preis", "Beitrag")),
        RegistryColumn("Turnus", "Billing interval",
                       ("Interval", "Zahlungsweise", "Rhythmus", "Frequency", "Zyklus")),
        RegistryColumn("Nächste Fälligkeit", "Next due date",
                       ("Fälligkeit", "Due date", "Next due", "Nächste Zahlung",
                        "Faelligkeit")),
        RegistryColumn("Kontakt", "Provider contact",
                       ("Contact", "Anbieter", "Provider", "Telefon", "E-Mail", "Email")),
    ),
    "medication_plan": (
        RegistryColumn("Medikament", "Trade name or medication",
                       ("Medikament", "Präparat", "Name", "Handelsname", "Arzneimittel")),
        RegistryColumn("Wirkstoff", "Active ingredient",
                       ("Wirkstoff", "Substanz", "Ingredient", "Active ingredient")),
        RegistryColumn("Dosierung", "Dose or strength",
                       ("Dosierung", "Dosis", "Stärke", "Menge", "Strength")),
        RegistryColumn("Einnahme", "Intake schedule or time",
                       ("Einnahme", "Einnahmezeit", "Tageszeit", "Schema", "Turnus", "Schedule")),
        RegistryColumn("Hinweis", "Application notes or indications",
                       ("Hinweis", "Grund", "Indikation", "Wirkung", "Anmerkung", "Notes")),
    ),
    "inventory": (
        RegistryColumn("Gegenstand", "Item or property",
                       ("Gegenstand", "Name", "Artikel", "Item", "Bezeichnung")),
        RegistryColumn("Lagerort", "Location or room",
                       ("Lagerort", "Ort", "Raum", "Zimmer", "Location")),
        RegistryColumn("Menge", "Quantity or count",
                       ("Menge", "Anzahl", "Stück", "Quantity", "Count")),
        RegistryColumn("Kategorie", "Category or type",
                       ("Kategorie", "Rubrik", "Typ", "Category", "Type")),
        RegistryColumn("Zustand", "Condition or status",
                       ("Zustand", "Status", "Condition")),
    ),
}

DATE_PATTERNS = (
    ("%Y-%m-%d", re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")),
    ("%d.%m.%Y", re.compile(r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b")),
)


def columns_from_parameters(value: Any, template: Any) -> tuple[RegistryColumn, ...]:
    """Build the column contract from an explicit list or a named template."""
    if value is None:
        if template is None:
            raise ValueError("document_registry requires columns or a column_template")
        if not isinstance(template, str) or template not in COLUMN_TEMPLATES:
            raise ValueError(
                "unknown column_template: choose one of "
                + ", ".join(sorted(COLUMN_TEMPLATES))
            )
        return COLUMN_TEMPLATES[template]
    if not isinstance(value, list) or not value:
        raise ValueError("columns must be a non-empty list")
    if len(value) > MAX_COLUMNS:
        raise ValueError(f"columns must not exceed {MAX_COLUMNS} entries")
    columns: list[RegistryColumn] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) - {"name", "description", "aliases"}:
            raise ValueError("each column needs name and may carry description and aliases")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("column name must be a non-empty string")
        if name.casefold() in seen:
            raise ValueError(f"duplicate column: {name}")
        seen.add(name.casefold())
        description = item.get("description", "")
        if not isinstance(description, str):
            raise ValueError("column description must be a string")
        aliases = item.get("aliases", [])
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise ValueError("column aliases must be non-empty strings")
        columns.append(
            RegistryColumn(name.strip(), description.strip(), tuple(a.strip() for a in aliases))
        )
    return tuple(columns)


def build_registry(
    sources: tuple[tuple[str, str], ...],
    texts: dict[str, str],
    columns: tuple[RegistryColumn, ...],
    *,
    topic_filter: tuple[str, ...] = (),
    structured_source_ids: frozenset[str] | None = None,
) -> RegistryTable:
    """Adapt the shared field primitive to the registry's own row contract."""
    rows, skipped = extract_fields(
        sources,
        texts,
        tuple(column.spec() for column in columns),
        topic_filter=topic_filter,
        max_rows=MAX_ROWS,
        structured_source_ids=structured_source_ids,
    )
    return RegistryTable(
        columns=columns,
        rows=tuple(
            RegistryRow(
                source_id=row.source_id,
                display_name=row.display_name,
                record_line=row.record_line,
                cells=tuple(
                    RegistryCell(
                        column=value.field,
                        value=value.value,
                        source_id=value.anchor.source_id if value.anchor else None,
                        line=value.anchor.line if value.anchor else None,
                        quote=value.quote,
                    )
                    for value in row.values
                ),
            )
            for row in rows
        ),
        skipped_source_ids=skipped,
    )


def registry_to_primitive(table: RegistryTable) -> dict[str, Any]:
    return {
        "schema": "nemofold.document-registry.v1",
        "columns": [
            {"name": column.name, "description": column.description,
             "aliases": list(column.aliases)}
            for column in table.columns
        ],
        "rows": [
            {
                "source_id": row.source_id,
                "display_name": row.display_name,
                "record_line": row.record_line,
                "cells": [
                    {
                        "column": cell.column,
                        "value": cell.value,
                        "source_id": cell.source_id,
                        "line": cell.line,
                        "quote": cell.quote,
                    }
                    for cell in row.cells
                ],
            }
            for row in table.rows
        ],
        "filled_cells": table.filled_cells,
        "empty_cells": table.empty_cells,
        "skipped_source_ids": list(table.skipped_source_ids),
    }


def registry_to_csv(table: RegistryTable) -> str:
    """Flatten the table, keeping each cell's anchor in its own column."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    has_record_lines = any(row.record_line is not None for row in table.rows)
    header = ["source_id", "display_name"]
    if has_record_lines:
        header.append("record_line")
    for column in table.columns:
        header.extend([column.name, f"{column.name} [source]"])
    writer.writerow(header)
    for row in table.rows:
        line = [row.source_id, row.display_name]
        if has_record_lines:
            line.append(row.record_line or "")
        for cell in row.cells:
            line.append(cell.value or "")
            line.append(
                f"{cell.source_id}:{cell.line}" if cell.filled else ""
            )
        writer.writerow(line)
    return buffer.getvalue()


def _parse_date(value: str) -> date | None:
    for fmt, pattern in DATE_PATTERNS:
        match = pattern.search(value)
        if match is None:
            continue
        try:
            return datetime.strptime(match.group(1), fmt).date()
        except ValueError:
            continue
    return None


def due_within(
    table: RegistryTable,
    *,
    column: str,
    reference: date,
    days: int,
) -> tuple[dict[str, Any], ...]:
    """List rows whose date cell falls inside the window, unparsable ones included.

    A date the parser cannot read is reported as unreadable rather than dropped,
    so a missed payment can never hide behind a silent parse failure.
    """
    results: list[dict[str, Any]] = []
    for row in table.rows:
        cell = next((item for item in row.cells if item.column == column), None)
        if cell is None or not cell.filled or cell.value is None:
            continue
        parsed = _parse_date(cell.value)
        if parsed is None:
            results.append(
                {
                    "source_id": row.source_id,
                    "display_name": row.display_name,
                    "value": cell.value,
                    "due_date": None,
                    "days_until": None,
                    "state": "unreadable_date",
                }
            )
            continue
        delta = (parsed - reference).days
        if delta < 0:
            state = "overdue"
        elif delta <= days:
            state = "due"
        else:
            continue
        results.append(
            {
                "source_id": row.source_id,
                "display_name": row.display_name,
                "value": cell.value,
                "due_date": parsed.isoformat(),
                "days_until": delta,
                "state": state,
            }
        )
    return tuple(results)
