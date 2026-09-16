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

Nothing here executes a query a caller did not declare. Standalone SQLite
reads use a read-only URI; the job reader hashes one byte snapshot and opens
that snapshot in memory with query-only enabled. Active SQLite sidecars are
refused because a main-file hash cannot bind their logical rows. Only the
tables a job names are read, and the reader refuses non-table objects.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from .document_extract import SourceHashMismatch, read_xml_member

STRUCTURED_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3", ".xlsx"})
MAX_ROWS_PER_TABLE = 2000
MAX_CELL_CHARS = 300
MAX_COLUMNS = 60
MAX_STRUCTURED_SOURCE_BYTES = 128 * 1024 * 1024
CONTACT_FIELDS = ("name", "class", "email", "phone", "note")

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")
_CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")
_STRUCTURED_ROW = re.compile(r"^Zeile \d+ · ")


class StructuredSourceError(ValueError):
    """Raised when a structured source cannot be read under its declared limits."""


class BoundStructuredSourceError(RuntimeError):
    """A selected, inventoried structured source cannot be safely rendered."""


@dataclass(frozen=True, slots=True)
class TableRendering:
    """A table rendered as anchored text, plus what had to be left out."""

    text: str
    row_count: int
    notes: tuple[str, ...]


def mask_structured_rows(text: str, selected_lines: tuple[int, ...]) -> str:
    """Keep only selected records while preserving every original line anchor."""
    lines = text.splitlines()
    row_lines = {number for number, line in enumerate(lines, start=1)
                 if _STRUCTURED_ROW.match(line)}
    if not selected_lines or not set(selected_lines) <= row_lines:
        raise ValueError("source_selected_lines_invalid")
    selected = set(selected_lines)
    masked = [
        line if number not in row_lines or number in selected else ""
        for number, line in enumerate(lines, start=1)
    ]
    return "\n".join(masked) + ("\n" if text.endswith("\n") else "")


def select_topic_rows(text: str, terms: tuple[str, ...]) -> tuple[str, tuple[int, ...]]:
    """Select matching table records, not a whole file because one row matched."""
    if not terms:
        return text, ()
    selected = tuple(
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if _STRUCTURED_ROW.match(line)
        and any(term.casefold() in line.casefold() for term in terms)
    )
    if not selected:
        return "", ()
    return mask_structured_rows(text, selected), selected


def _cell(value: object) -> tuple[str, bool]:
    if value is None:
        return "", False
    rendered = " ".join(str(value).split()).replace("·", "∙")
    return rendered[:MAX_CELL_CHARS], len(rendered) > MAX_CELL_CHARS


def _label(value: object) -> str:
    """A source column name cannot inject our line/field separators."""
    rendered = " ".join(str(value).split())
    for separator in ("·", "|", ":"):
        rendered = rendered.replace(separator, " ")
    return " ".join(rendered.split())[:MAX_CELL_CHARS]


def _render_rows(
    title: str, columns: tuple[str, ...], rows: tuple[tuple[object, ...], ...]
) -> TableRendering:
    """One row per line, every cell labelled, so a line anchor names a record.

    The label form is what lets the existing field extraction read these rows
    without knowing they came from a table at all.
    """
    notes: list[str] = []
    labelled_columns: list[str] = []
    for index, column in enumerate(columns, start=1):
        original_label = " ".join(str(column).split())
        if len(original_label) > MAX_CELL_CHARS:
            notes.append(
                f"column header {index} exceeded {MAX_CELL_CHARS} characters and was truncated."
            )
        labelled_columns.append(_label(column) or f"Spalte {index}")
    columns = tuple(labelled_columns)
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
    truncated_cells: dict[int, list[int]] = {}
    for number, row in enumerate(kept, start=1):
        pairs: list[str] = []
        for index, (column, value) in enumerate(
            zip(columns, row[: len(columns)], strict=False), start=1
        ):
            rendered, truncated = _cell(value)
            pairs.append(f"{column}: {rendered}")
            if truncated:
                truncated_cells.setdefault(index, []).append(number)
        lines.append(f"Zeile {number} · " + " · ".join(pairs))
    for index, row_numbers in sorted(truncated_cells.items()):
        notes.append(
            f"{len(row_numbers)} cell(s) in column {index} exceeded "
            f"{MAX_CELL_CHARS} characters and were truncated; "
            f"first affected row {row_numbers[0]}."
        )
    return TableRendering(
        text="\n".join(lines) + "\n",
        row_count=len(kept),
        notes=tuple(f"{title}: {note}" for note in notes),
    )


# --------------------------------------------------------------------------- #
# SQLite
# --------------------------------------------------------------------------- #


def _sqlite_tables(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = connection.execute("PRAGMA table_list").fetchall()
    if not rows:
        raise StructuredSourceError("SQLite table classification unavailable")
    return tuple(
        sorted(
            str(row[1]) for row in rows
            if row[0] == "main" and row[2] == "table"
            and not str(row[1]).startswith("sqlite_")
        )
    )


def sqlite_tables(path: str | Path) -> tuple[str, ...]:
    """List the plain tables a read-only connection can see."""
    uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            return _sqlite_tables(connection)
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise StructuredSourceError(f"cannot read SQLite source: {exc}") from exc


def read_sqlite(
    path: str | Path,
    *,
    tables: tuple[str, ...] = (),
    max_rows: int = MAX_ROWS_PER_TABLE,
    data: bytes | None = None,
) -> TableRendering:
    """Render the declared tables of a read-only SQLite file.

    An empty ``tables`` reads every plain table, which is the honest default for
    a file a person deliberately approved. A named table that does not exist is
    reported rather than silently skipped, because a job that asked for it and
    got nothing back should not read as a job that found nothing.
    """
    uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(":memory:") if data is not None else sqlite3.connect(
            uri, uri=True
        )
        if data is not None:
            if not hasattr(connection, "deserialize"):
                raise BoundStructuredSourceError("sqlite_deserialize_unavailable")
            connection.deserialize(data)
            connection.execute("PRAGMA query_only=ON")
        available = _sqlite_tables(connection)
        wanted = tables or available
        notes: list[str] = []
        missing = [name for name in wanted if name not in available]
        if missing:
            notes.append(
                f"table(s) not present in this file and therefore not read: {', '.join(missing)}"
            )
        parts: list[str] = []
        total = 0
        for name in wanted:
            if name not in available:
                continue
            if not _IDENTIFIER.fullmatch(name):
                notes.append(f"table name refused as an identifier: {name}")
                continue
            # The name is checked against the file's own table list and against
            # the identifier shape before it is quoted, so no caller string ever
            # reaches SQL unvalidated.
            columns_cursor = connection.execute(f'SELECT * FROM "{name}" LIMIT 0')
            columns = tuple(str(item[0]) for item in columns_cursor.description or ())
            if not columns or len(columns) > MAX_COLUMNS:
                raise StructuredSourceError("SQLite table exceeds column ceiling")
            limit = min(max(0, int(max_rows)), MAX_ROWS_PER_TABLE)
            order = ", ".join(str(index) for index in range(1, len(columns) + 1))
            count = int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            cursor = connection.execute(
                f'SELECT * FROM "{name}" ORDER BY {order} LIMIT {limit}'
            )
            rows = tuple(tuple(row) for row in cursor.fetchall())
            rendering = _render_rows(f"Tabelle {name}", columns, rows)
            parts.append(rendering.text)
            notes.extend(rendering.notes)
            if count > rendering.row_count:
                notes.append(
                    f"Tabelle {name}: {count - rendering.row_count} row(s) beyond the ceiling of "
                    f"{limit} were not rendered."
                )
            total += rendering.row_count
        if not parts:
            notes.append("no declared table was readable in this SQLite source.")
        return TableRendering(text="\n".join(parts), row_count=total, notes=tuple(notes))
    except sqlite3.Error as exc:
        raise StructuredSourceError(f"cannot read SQLite source: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #


def read_csv(
    path: str | Path, *, max_rows: int = MAX_ROWS_PER_TABLE, data: bytes | None = None
) -> TableRendering:
    """Render a delimited file with its header as column labels."""
    raw = data.decode("utf-8-sig") if data is not None else Path(path).read_text(
        encoding="utf-8-sig"
    )
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(raw), dialect)
    nonempty = (tuple(row) for row in reader if any(str(cell).strip() for cell in row))
    header_row = next(nonempty, None)
    if header_row is None:
        return TableRendering(text="", row_count=0, notes=("the file holds no row.",))
    header = tuple(
        str(cell).strip() or f"Spalte {index + 1}"
        for index, cell in enumerate(header_row)
    )
    kept: list[tuple[str, ...]] = []
    total = 0
    limit = min(max(0, int(max_rows)), MAX_ROWS_PER_TABLE)
    for row in nonempty:
        total += 1
        if len(kept) < limit:
            kept.append(row)
    rendering = _render_rows(f"Tabelle {Path(path).stem}", header, tuple(kept))
    if total <= rendering.row_count:
        return rendering
    return TableRendering(
        text=rendering.text,
        row_count=rendering.row_count,
        notes=rendering.notes + (
            f"{total - rendering.row_count} row(s) beyond the ceiling of {limit} "
            "were not rendered.",
        ),
    )


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


def read_xlsx(
    path: str | Path, *, max_rows: int = MAX_ROWS_PER_TABLE, data: bytes | None = None
) -> TableRendering:
    """Render the first worksheet of a workbook without a third-party reader.

    The same zipfile-and-XML route the DOCX and ODT readers already take. It
    keeps the package free of a spreadsheet dependency for the sake of reading a
    grid of strings, which is all a corpus source needs from one.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data) if data is not None else path) as archive:
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
    total_rows = 0
    limit = min(max(0, int(max_rows)), MAX_ROWS_PER_TABLE)
    for row in sheet.iter():
        if row.tag.rsplit("}", 1)[-1] != "row":
            continue
        values: dict[int, str] = {}
        for cell in row:
            if cell.tag.rsplit("}", 1)[-1] != "c":
                continue
            reference = cell.attrib.get("r", "")
            column = _column_index(reference)
            if column >= MAX_COLUMNS:
                raise StructuredSourceError("XLSX cell beyond column ceiling")
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
            values[column] = text
        if not values:
            continue
        total_rows += 1
        if len(grid) <= limit:
            width = max(values) + 1
            grid.append([values.get(index, "") for index in range(width)])
    if not grid:
        return TableRendering(text="", row_count=0, notes=("the workbook holds no row.",))
    header = tuple(cell.strip() or f"Spalte {index + 1}" for index, cell in enumerate(grid[0]))
    rendering = _render_rows(
        f"Tabelle {Path(path).stem}", header, tuple(tuple(row) for row in grid[1:])
    )
    omitted = max(0, total_rows - 1 - rendering.row_count)
    if not omitted:
        return rendering
    return TableRendering(
        text=rendering.text,
        row_count=rendering.row_count,
        notes=rendering.notes + (
            f"{omitted} row(s) beyond the ceiling of {limit} were not rendered.",
        ),
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
    expected_sha256: str | None = None,
) -> TableRendering:
    """Render one verified byte snapshot, or say the source is not bound.

    SQLite WAL and rollback-journal sidecars are not part of the inventory
    digest. Never turn a partial main-file view into an executed claim.
    """
    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix not in {".db", ".sqlite", ".sqlite3", ".xlsx", ".csv"}:
        raise StructuredSourceError(f"not a structured source: {suffix or '<none>'}")
    if source.is_symlink():
        raise SourceHashMismatch("source_symlink_unbound")
    resolved = source.resolve()
    sidecars = tuple(Path(str(resolved) + ending) for ending in ("-wal", "-shm", "-journal"))
    if suffix in {".db", ".sqlite", ".sqlite3"} and any(
        item.exists() or item.is_symlink() for item in sidecars
    ):
        raise SourceHashMismatch("sqlite_sidecar_unbound")
    with source.open("rb") as stream:
        data = stream.read(MAX_STRUCTURED_SOURCE_BYTES + 1)
    if len(data) > MAX_STRUCTURED_SOURCE_BYTES:
        if expected_sha256 is not None:
            raise BoundStructuredSourceError("source_byte_limit")
        raise StructuredSourceError("source_byte_limit")
    if expected_sha256 is not None and hashlib.sha256(data).hexdigest() != expected_sha256:
        raise SourceHashMismatch("source_hash_mismatch")
    if suffix in {".db", ".sqlite", ".sqlite3"} and any(
        item.exists() or item.is_symlink() for item in sidecars
    ):
        raise SourceHashMismatch("sqlite_sidecar_unbound")
    try:
        if suffix in {".db", ".sqlite", ".sqlite3"}:
            rendering = read_sqlite(path, tables=tables, max_rows=max_rows, data=data)
        elif suffix == ".xlsx":
            rendering = read_xlsx(path, max_rows=max_rows, data=data)
        elif suffix == ".csv":
            rendering = read_csv(path, max_rows=max_rows, data=data)
        else:
            raise AssertionError("unsupported structured suffix")
    except (StructuredSourceError, UnicodeError) as exc:
        if expected_sha256 is not None:
            raise BoundStructuredSourceError("structured_source_unreadable") from exc
        raise
    if suffix in {".db", ".sqlite", ".sqlite3"} and any(
        item.exists() or item.is_symlink() for item in sidecars
    ):
        raise SourceHashMismatch("sqlite_sidecar_unbound")
    return rendering
