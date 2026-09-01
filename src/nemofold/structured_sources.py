"""K1: structured local sources read as anchored corpus text.

A database row and a paragraph are the same kind of evidence here: something a
source says, at a place you can point at. So structured sources are not given a
parallel pipeline. They are rendered into deterministic labelled text, and the
existing machinery - field extraction, statements, entity resolution, timelines,
corroboration - works on them unchanged, with the line number as the anchor.

That only holds if the rendering is stable, so every reader here sorts what the
format leaves unordered and never emits a value the source did not contain. Two
runs over the same file produce the same lines, which is what makes "row 14 of
table `rezepte`" a citation rather than a description.

Nothing here executes a query a caller did not declare. SQLite is opened
read-only through a URI, only the tables a job names are read, and the reader
refuses anything that is not a plain table.
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from .document_extract import read_xml_member

STRUCTURED_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3", ".xlsx"})
MAX_ROWS_PER_TABLE = 2000
MAX_CELL_CHARS = 300
MAX_COLUMNS = 60
CONTACT_FIELDS = ("name", "class", "email", "phone", "note")

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")
_CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")


class StructuredSourceError(ValueError):
    """Raised when a structured source cannot be read under its declared limits."""


@dataclass(frozen=True, slots=True)
class TableRendering:
    """A table rendered as anchored text, plus what had to be left out."""

    text: str
    row_count: int
    notes: tuple[str, ...]


def _cell(value: object) -> str:
    if value is None:
        return ""
    rendered = " ".join(str(value).split())
    return rendered[:MAX_CELL_CHARS]


def _render_rows(
    title: str, columns: tuple[str, ...], rows: tuple[tuple[object, ...], ...]
) -> TableRendering:
    """One row per line, every cell labelled, so a line anchor names a record.

    The label form is what lets the existing field extraction read these rows
    without knowing they came from a table at all.
    """
    notes: list[str] = []
    if len(columns) > MAX_COLUMNS:
        notes.append(
            f"{len(columns) - MAX_COLUMNS} column(s) beyond the ceiling of {MAX_COLUMNS} "
            "were not rendered."
        )
        columns = columns[:MAX_COLUMNS]
    kept = rows[:MAX_ROWS_PER_TABLE]
    if len(rows) > len(kept):
        notes.append(
            f"{len(rows) - len(kept)} row(s) beyond the ceiling of {MAX_ROWS_PER_TABLE} "
            "were not rendered."
        )
    lines = [f"# {title}", "", "Spalten: " + " | ".join(columns), ""]
    for number, row in enumerate(kept, start=1):
        pairs = [
            f"{column}: {_cell(value)}"
            for column, value in zip(columns, row[: len(columns)], strict=False)
        ]
        lines.append(f"Zeile {number} · " + " · ".join(pairs))
    return TableRendering(
        text="\n".join(lines) + "\n", row_count=len(kept), notes=tuple(notes)
    )


# --------------------------------------------------------------------------- #
# SQLite
# --------------------------------------------------------------------------- #


def sqlite_tables(path: str | Path) -> tuple[str, ...]:
    """List the plain tables a read-only connection can see."""
    uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
    except sqlite3.Error as exc:
        raise StructuredSourceError(f"cannot read SQLite source: {exc}") from exc
    return tuple(str(row[0]) for row in rows)


def read_sqlite(
    path: str | Path, *, tables: tuple[str, ...] = (), max_rows: int = MAX_ROWS_PER_TABLE
) -> TableRendering:
    """Render the declared tables of a read-only SQLite file.

    An empty ``tables`` reads every plain table, which is the honest default for
    a file a person deliberately approved. A named table that does not exist is
    reported rather than silently skipped, because a job that asked for it and
    got nothing back should not read as a job that found nothing.
    """
    available = sqlite_tables(path)
    wanted = tables or available
    notes: list[str] = []
    missing = [name for name in wanted if name not in available]
    if missing:
        notes.append(
            f"table(s) not present in this file and therefore not read: {', '.join(missing)}"
        )
    parts: list[str] = []
    total = 0
    uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        for name in wanted:
            if name not in available:
                continue
            if not _IDENTIFIER.fullmatch(name):
                notes.append(f"table name refused as an identifier: {name}")
                continue
            # The name is checked against the file's own table list and against
            # the identifier shape before it is quoted, so no caller string ever
            # reaches SQL unvalidated.
            cursor = connection.execute(f'SELECT * FROM "{name}" LIMIT {int(max_rows) + 1}')
            columns = tuple(str(item[0]) for item in cursor.description or ())
            rows = tuple(tuple(row) for row in cursor.fetchall())
            rendering = _render_rows(f"Tabelle {name}", columns, rows)
            parts.append(rendering.text)
            notes.extend(rendering.notes)
            total += rendering.row_count
    if not parts:
        notes.append("no declared table was readable in this SQLite source.")
    return TableRendering(text="\n".join(parts), row_count=total, notes=tuple(notes))


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #


def read_csv(path: str | Path, *, max_rows: int = MAX_ROWS_PER_TABLE) -> TableRendering:
    """Render a delimited file with its header as column labels."""
    raw = Path(path).read_text(encoding="utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(raw), dialect)
    rows = [tuple(row) for row in reader if any(str(cell).strip() for cell in row)]
    if not rows:
        return TableRendering(text="", row_count=0, notes=("the file holds no row.",))
    header = tuple(str(cell).strip() or f"Spalte {index + 1}" for index, cell in enumerate(rows[0]))
    return _render_rows(f"Tabelle {Path(path).stem}", header, tuple(rows[1:max_rows + 1]))


# --------------------------------------------------------------------------- #
# XLSX, through the standard library
# --------------------------------------------------------------------------- #


def _column_index(reference: str) -> int:
    match = _CELL_REF.match(reference)
    if match is None:
        return 0
    index = 0
    for character in match.group(1):
        index = index * 26 + (ord(character) - 64)
    return index - 1


def read_xlsx(path: str | Path, *, max_rows: int = MAX_ROWS_PER_TABLE) -> TableRendering:
    """Render the first worksheet of a workbook without a third-party reader.

    The same zipfile-and-XML route the DOCX and ODT readers already take. It
    keeps the package free of a spreadsheet dependency for the sake of reading a
    grid of strings, which is all a corpus source needs from one.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                root = ElementTree.fromstring(
                    read_xml_member(archive, "xl/sharedStrings.xml")
                )
                for item in root:
                    shared.append("".join(item.itertext()))
            sheets = sorted(name for name in names if name.startswith("xl/worksheets/sheet"))
            if not sheets:
                raise StructuredSourceError(f"workbook holds no worksheet: {Path(path).name}")
            sheet = ElementTree.fromstring(read_xml_member(archive, sheets[0]))
    except (KeyError, OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise StructuredSourceError(
            f"invalid or refused XLSX workbook: {Path(path).name} ({exc})"
        ) from exc

    grid: list[list[str]] = []
    for row in sheet.iter():
        if row.tag.rsplit("}", 1)[-1] != "row":
            continue
        values: dict[int, str] = {}
        for cell in row:
            if cell.tag.rsplit("}", 1)[-1] != "c":
                continue
            reference = cell.attrib.get("r", "")
            kind = cell.attrib.get("t", "")
            text = ""
            for child in cell:
                tag = child.tag.rsplit("}", 1)[-1]
                if tag == "v":
                    text = child.text or ""
                elif tag == "is":
                    text = "".join(child.itertext())
            if kind == "s" and text.isdigit() and int(text) < len(shared):
                text = shared[int(text)]
            values[_column_index(reference)] = text
        if not values:
            continue
        width = max(values) + 1
        grid.append([values.get(index, "") for index in range(width)])
        if len(grid) > max_rows + 1:
            break
    if not grid:
        return TableRendering(text="", row_count=0, notes=("the workbook holds no row.",))
    header = tuple(cell.strip() or f"Spalte {index + 1}" for index, cell in enumerate(grid[0]))
    return _render_rows(
        f"Tabelle {Path(path).stem}", header, tuple(tuple(row) for row in grid[1:max_rows + 1])
    )


# --------------------------------------------------------------------------- #
# Contacts
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Contact:
    """One entry of the local contact book, with the class it belongs to."""

    name: str
    contact_class: str
    email: str
    phone: str
    note: str
    line: int


def read_contacts(path: str | Path) -> tuple[tuple[Contact, ...], tuple[str, ...]]:
    """Read the local contact book: one contact per line, labelled fields.

    The class is what the outbound rights later hang on, so a contact without
    one is not given a default. It is reported, and the delivery side treats an
    unclassified recipient as the strictest case rather than the friendliest.
    """
    contacts: list[Contact] = []
    notes: list[str] = []
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields: dict[str, str] = {}
        for part in line.split("·"):
            label, separator, value = part.partition(":")
            if not separator:
                continue
            key = label.strip().casefold()
            if key in CONTACT_FIELDS:
                fields[key] = value.strip()
        if "name" not in fields:
            notes.append(f"line {number} carries no name and was not read as a contact.")
            continue
        if "class" not in fields:
            notes.append(
                f"line {number} ({fields['name']}) declares no class; delivery will treat "
                "this recipient as the strictest case."
            )
        contacts.append(
            Contact(
                name=fields["name"],
                contact_class=fields.get("class", ""),
                email=fields.get("email", ""),
                phone=fields.get("phone", ""),
                note=fields.get("note", ""),
                line=number,
            )
        )
    return tuple(contacts), tuple(notes)


def contacts_text(contacts: tuple[Contact, ...]) -> str:
    """Render contacts back into anchored corpus text."""
    lines = ["# Kontaktbestand", ""]
    lines.extend(
        f"Zeile {index} · name: {item.name} · class: {item.contact_class or '(ohne Klasse)'}"
        f" · email: {item.email} · phone: {item.phone}"
        for index, item in enumerate(contacts, start=1)
    )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# The one entry point the corpus reader needs
# --------------------------------------------------------------------------- #


def read_structured(
    path: str | Path,
    *,
    tables: tuple[str, ...] = (),
    max_rows: int = MAX_ROWS_PER_TABLE,
) -> TableRendering:
    """Render whichever structured format this path is, or say it is not one."""
    suffix = Path(path).suffix.casefold()
    if suffix in {".db", ".sqlite", ".sqlite3"}:
        return read_sqlite(path, tables=tables, max_rows=max_rows)
    if suffix == ".xlsx":
        return read_xlsx(path, max_rows=max_rows)
    if suffix == ".csv":
        return read_csv(path, max_rows=max_rows)
    raise StructuredSourceError(f"not a structured source: {suffix or '<none>'}")
