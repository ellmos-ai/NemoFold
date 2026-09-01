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


def test_a_workbook_is_read_without_a_spreadsheet_dependency(tmp_path) -> None:
    import openpyxl

    book = tmp_path / "register.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Police", "Tarif", "Beitrag"])
    sheet.append(["KV-2026-0447", "Teilkasko", 148])
    workbook.save(book)

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
