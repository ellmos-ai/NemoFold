from __future__ import annotations

import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.document_extract import MAX_XML_MEMBER_BYTES, read_xml_member
from nemofold.job_io import parse_job_payload
from nemofold.structured_sources import (
    StructuredSourceError,
    read_contacts,
    read_csv,
    read_sqlite,
    read_structured,
    read_xlsx,
    sqlite_tables,
)


def _mediplaner(path: Path) -> Path:
    """A recipe database of the shape a medication planner would keep."""
    database = path / "mediplaner.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE rezepte (id INTEGER, praeparat TEXT, dosis TEXT, "
            "arzt TEXT, ausgestellt TEXT)"
        )
        connection.executemany(
            "INSERT INTO rezepte VALUES (?, ?, ?, ?, ?)",
            [
                (1, "Beispirol", "1-0-1", "Dr. Halvorsen", "2026-02-03"),
                (2, "Musterazol", "0-0-1", "Dr. Brandt", "2026-03-11"),
            ],
        )
        connection.execute("CREATE TABLE notizen (id INTEGER, text TEXT)")
        connection.execute("INSERT INTO notizen VALUES (1, 'Nachfrage offen')")
    return database


# --------------------------------------------------------------------------- #
# SQLite is read-only, declared, and anchored
# --------------------------------------------------------------------------- #


def test_a_recipe_database_becomes_anchored_lines(tmp_path) -> None:
    database = _mediplaner(tmp_path)

    rendering = read_sqlite(database)

    assert rendering.row_count == 3
    assert "Tabelle rezepte" in rendering.text
    # Every row is one line with labelled cells, which is what makes a line
    # number a citation rather than a description.
    line = next(
        item for item in rendering.text.splitlines() if "Beispirol" in item
    )
    assert line.startswith("Zeile 1 · ")
    assert "praeparat: Beispirol" in line and "dosis: 1-0-1" in line


def test_only_the_declared_tables_are_read(tmp_path) -> None:
    database = _mediplaner(tmp_path)

    rendering = read_sqlite(database, tables=("rezepte",))

    assert "Tabelle rezepte" in rendering.text
    assert "Tabelle notizen" not in rendering.text
    assert rendering.row_count == 2


def test_a_table_that_does_not_exist_is_reported_not_silently_skipped(tmp_path) -> None:
    database = _mediplaner(tmp_path)

    rendering = read_sqlite(database, tables=("rezepte", "abrechnungen"))

    assert "abrechnungen" in rendering.notes[0]
    assert "not present in this file" in rendering.notes[0]


def test_the_source_is_opened_read_only(tmp_path) -> None:
    database = _mediplaner(tmp_path)

    # The same URI the reader uses must refuse a write.
    uri = f"file:{database.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection, pytest.raises(sqlite3.OperationalError):
        connection.execute("INSERT INTO rezepte VALUES (3, 'X', 'Y', 'Z', 'A')")
    assert "rezepte" in sqlite_tables(database)


def test_an_unreadable_file_is_refused_with_a_reason(tmp_path) -> None:
    broken = tmp_path / "kaputt.sqlite"
    broken.write_text("no database here", encoding="utf-8")

    with pytest.raises(StructuredSourceError, match="cannot read SQLite source"):
        read_sqlite(broken)


# --------------------------------------------------------------------------- #
# CSV and XLSX
# --------------------------------------------------------------------------- #


def test_a_subscription_registry_csv_becomes_labelled_rows(tmp_path) -> None:
    registry = tmp_path / "abos.csv"
    registry.write_text(
        "Dienst;Tarif;Betrag;Turnus\nBeispielstream;Familie;17,99;monatlich\n"
        "Musterpost;Basis;4,50;monatlich\n",
        encoding="utf-8",
    )

    rendering = read_csv(registry)

    assert rendering.row_count == 2
    assert "Dienst: Beispielstream" in rendering.text
    assert "Turnus: monatlich" in rendering.text


def _shared_string_workbook(path: Path, rows: tuple[tuple[str, ...], ...]) -> Path:
    """A workbook in the shape Excel writes: text in a shared string table.

    Built by hand rather than with a spreadsheet library, because a test whose
    subject is reading without that dependency cannot need it to produce its own
    input - which is exactly how this one passed locally and failed on a runner
    that had never installed one.
    """
    values: list[str] = []
    for row in rows:
        for cell in row:
            if not cell.isdigit() and cell not in values:
                values.append(cell)

    def cell_xml(column: int, line: int, text: str) -> str:
        reference = f"{chr(ord('A') + column)}{line}"
        if text.isdigit():
            return f'<c r="{reference}"><v>{text}</v></c>'
        return f'<c r="{reference}" t="s"><v>{values.index(text)}</v></c>'

    sheet = "".join(
        f'<row r="{line}">'
        + "".join(cell_xml(column, line, cell) for column, cell in enumerate(row))
        + "</row>"
        for line, row in enumerate(rows, start=1)
    )
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="rels" ContentType='
            '"application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns='
            '"http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Register" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns='
            '"http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>'
        ),
        "xl/sharedStrings.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'count="{len(values)}" uniqueCount="{len(values)}">'
            + "".join(f"<si><t>{value}</t></si>" for value in values)
            + "</sst>"
        ),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{sheet}</sheetData></worksheet>"
        ),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
    return path


def test_a_workbook_is_read_without_a_spreadsheet_dependency(tmp_path) -> None:
    book = _shared_string_workbook(
        tmp_path / "register.xlsx",
        (("Police", "Tarif", "Beitrag"), ("KV-2026-0447", "Teilkasko", "148")),
    )

    rendering = read_xlsx(book)

    assert rendering.row_count == 1
    assert "Police: KV-2026-0447" in rendering.text
    assert "Beitrag: 148" in rendering.text


def test_a_shared_string_table_is_resolved_and_not_read_as_a_number(tmp_path) -> None:
    """The index into the table looks exactly like a numeric cell value."""
    book = _shared_string_workbook(
        tmp_path / "indexe.xlsx",
        (("Feld",), ("Erster",), ("Zweiter",)),
    )

    rendering = read_xlsx(book)

    # Reading these as 0 and 1 would be a plausible-looking table of nonsense,
    # which is worse than a workbook that refuses to open.
    assert "Feld: Erster" in rendering.text
    assert "Feld: Zweiter" in rendering.text


def test_the_hand_built_fixture_is_a_workbook_a_real_reader_accepts(tmp_path) -> None:
    """Guards the replacement itself, wherever a spreadsheet library exists.

    A fixture our own reader happens to tolerate would prove nothing about
    reading what people actually have, so this checks the shape against an
    independent reader instead of against ourselves.
    """
    openpyxl = pytest.importorskip("openpyxl")
    book = _shared_string_workbook(
        tmp_path / "register.xlsx",
        (("Police", "Tarif", "Beitrag"), ("KV-2026-0447", "Teilkasko", "148")),
    )

    sheet = openpyxl.load_workbook(book).active

    assert [list(row) for row in sheet.iter_rows(values_only=True)] == [
        ["Police", "Tarif", "Beitrag"],
        ["KV-2026-0447", "Teilkasko", 148],
    ]


def test_what_this_workspace_writes_it_can_also_read_back(tmp_path) -> None:
    """The floor that holds where no spreadsheet library is installed.

    Our own writer uses inline strings rather than a shared table, so this is a
    different path through the reader than the fixture above. It proves the two
    halves agree; whether a real spreadsheet application agrees is what the
    openpyxl cross-checks establish, wherever that package is present.
    """
    from nemofold.delivery import workbook_bytes

    book = tmp_path / "eigen.xlsx"
    book.write_bytes(
        workbook_bytes(("Police", "Beitrag"), (("KV-2026-0447", "148"),))
    )

    rendering = read_xlsx(book)

    assert rendering.row_count == 1
    assert "Police: KV-2026-0447" in rendering.text
    assert "Beitrag: 148" in rendering.text


def test_read_structured_refuses_a_format_it_does_not_handle(tmp_path) -> None:
    plain = tmp_path / "note.txt"
    plain.write_text("x", encoding="utf-8")

    with pytest.raises(StructuredSourceError, match="not a structured source"):
        read_structured(plain)


# --------------------------------------------------------------------------- #
# An approved root holds untrusted files
# --------------------------------------------------------------------------- #


def test_an_xml_part_with_a_document_type_declaration_is_refused(tmp_path) -> None:
    hostile = tmp_path / "bomb.xlsx"
    payload = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        b"<worksheet><sheetData/></worksheet>"
    )
    with zipfile.ZipFile(hostile, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", payload)

    # Entity expansion is how a small file becomes an out-of-memory condition,
    # and an approved root is exactly where an untrusted file lives.
    with pytest.raises(StructuredSourceError, match="invalid or refused"):
        read_xlsx(hostile)


def test_an_oversized_xml_part_is_refused_before_it_is_decompressed(tmp_path) -> None:
    archive_path = tmp_path / "big.xlsx"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"<a/>")
    with zipfile.ZipFile(archive_path) as archive:
        info = archive.getinfo("xl/worksheets/sheet1.xml")
        info.file_size = MAX_XML_MEMBER_BYTES + 1
        with pytest.raises(ValueError, match="beyond the"):
            read_xml_member(archive, "xl/worksheets/sheet1.xml")


# --------------------------------------------------------------------------- #
# Contacts carry the class the delivery rights hang on
# --------------------------------------------------------------------------- #


def test_contacts_are_read_with_their_class(tmp_path) -> None:
    book = tmp_path / "kontakte.txt"
    book.write_text(
        "# Kontaktbestand\n"
        "name: Ines Brandt · class: familie · email: ines@example.invalid\n"
        "name: Robert Ostwald · class: dienstlich · email: ostwald@example.invalid\n",
        encoding="utf-8",
    )

    contacts, notes = read_contacts(book)

    assert [item.name for item in contacts] == ["Ines Brandt", "Robert Ostwald"]
    assert contacts[0].contact_class == "familie"
    assert notes == ()


def test_a_contact_without_a_class_is_reported_as_the_strictest_case(tmp_path) -> None:
    book = tmp_path / "kontakte.txt"
    book.write_text("name: Unbekannt Jemand · email: x@example.invalid\n", encoding="utf-8")

    contacts, notes = read_contacts(book)

    assert contacts[0].contact_class == ""
    assert "strictest case" in notes[0]


# --------------------------------------------------------------------------- #
# The corpus reads them like any other source
# --------------------------------------------------------------------------- #


def test_a_database_is_analysed_as_part_of_the_corpus(tmp_path) -> None:
    documents = tmp_path / "akte"
    documents.mkdir()
    _mediplaner(documents)
    shutil.copy(
        Path(__file__).resolve().parents[2] / "examples" / "synthetic-case"
        / "polizeibericht-2026-03-16.md",
        documents / "bericht.md",
    )

    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "corpus_query",
            "input_roots": [str(documents)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "terms": ["Beispirol"],
                "source_tables": ["rezepte"],
                "formats": ["md"],
            },
        },
        base_dir=tmp_path,
    )
    result = run_job(job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="structured")

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["match_count"] >= 1
    import json

    payload = json.loads(
        (tmp_path / "out" / "structured.corpus-query.json").read_text(encoding="utf-8")
    )
    match = next(item for item in payload["matches"] if "Beispirol" in item["statement"])
    # The database row is quoted with a line anchor, exactly like a paragraph.
    assert match["anchors"][0]["source_id"]
    assert match["anchors"][0]["line"] > 0
    assert "praeparat: Beispirol" in match["statement"]
