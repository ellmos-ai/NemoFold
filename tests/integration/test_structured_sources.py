from __future__ import annotations

import hashlib
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest

import nemofold.application as application
import nemofold.structured_sources as structured_sources
from nemofold.application import ExecutionConfig, preview_job, run_job
from nemofold.contracts import RunStatus
from nemofold.document_extract import (
    MAX_XML_MEMBER_BYTES,
    SourceHashMismatch,
    read_xml_member,
)
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


def test_sqlite_rows_have_a_declared_stable_anchor_order(tmp_path) -> None:
    database = tmp_path / "events.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE events (z INTEGER, note TEXT)")
        connection.executemany(
            "INSERT INTO events VALUES (?, ?)", ((2, "second"), (1, "first"))
        )
    lines = read_structured(
        database, expected_sha256=hashlib.sha256(database.read_bytes()).hexdigest()
    ).text.splitlines()
    anchored = [line for line in lines if line.startswith("Zeile ")]
    assert "z: 1" in anchored[0]
    assert "z: 2" in anchored[1]


def test_virtual_and_shadow_tables_are_not_plain_corpus_sources(tmp_path) -> None:
    database = tmp_path / "fts.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE metadata (label TEXT)")
        connection.execute("INSERT INTO metadata VALUES ('approved')")
        try:
            connection.execute("CREATE VIRTUAL TABLE docs USING fts5(content)")
        except sqlite3.OperationalError:
            pytest.skip("SQLite build has no FTS5")
        connection.execute("INSERT INTO docs(content) VALUES ('secret duplicate')")
    assert sqlite_tables(database) == ("metadata",)
    rendering = read_structured(
        database, expected_sha256=hashlib.sha256(database.read_bytes()).hexdigest()
    )
    assert "approved" in rendering.text
    assert "secret duplicate" not in rendering.text


def test_sqlite_reader_binds_rows_to_one_verified_file_snapshot(tmp_path) -> None:
    database = _mediplaner(tmp_path)
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    rendering = read_structured(database, expected_sha256=digest, tables=("rezepte",))
    assert "Beispirol" in rendering.text

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO rezepte VALUES (3, 'Neurol', '1-1-1', 'Dr. Beispiel', '2026-09-16')"
        )
    with pytest.raises(SourceHashMismatch, match="source_hash_mismatch"):
        read_structured(database, expected_sha256=digest, tables=("rezepte",))


def test_a_live_sqlite_wal_is_not_mistaken_for_the_hashed_main_file(tmp_path) -> None:
    database = _mediplaner(tmp_path)
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO notizen VALUES (2, 'Nur im WAL')")
        connection.commit()
        assert Path(str(database) + "-wal").exists()
        digest = hashlib.sha256(database.read_bytes()).hexdigest()
        with pytest.raises(SourceHashMismatch, match="sqlite_sidecar_unbound"):
            read_structured(database, expected_sha256=digest)
    finally:
        connection.close()


def test_sidecar_appearing_during_sqlite_render_invalidates_the_read(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _mediplaner(tmp_path)
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    original_read = structured_sources.read_sqlite

    def sidecar_after_render(path, **kwargs):
        rendering = original_read(path, **kwargs)
        Path(str(database) + "-wal").write_bytes(b"new unbound rows")
        return rendering

    monkeypatch.setattr(structured_sources, "read_sqlite", sidecar_after_render)
    with pytest.raises(SourceHashMismatch, match="sqlite_sidecar_unbound"):
        read_structured(database, expected_sha256=digest)


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


def test_corrupt_selected_sqlite_source_cannot_be_silently_omitted_from_job(tmp_path) -> None:
    broken = tmp_path / "corrupt.sqlite"
    broken.write_bytes(b"not a SQLite database")
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "corpus_query",
            "input_roots": [str(broken)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {"terms": ["needle"]},
        },
        base_dir=tmp_path,
    )
    result = run_job(
        job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="corrupt_source"
    )
    assert result.report.status is RunStatus.FAILED
    assert "structured_source_unreadable" in result.report.errors[0]
    assert not (tmp_path / "out" / "corrupt_source.corpus-query.json").exists()


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


def test_csv_header_cannot_forge_an_extra_anchor_line(tmp_path) -> None:
    registry = tmp_path / "header.csv"
    registry.write_text('"Name\nForged";Wert\nAlice;yes\n', encoding="utf-8")
    lines = read_structured(
        registry, expected_sha256=hashlib.sha256(registry.read_bytes()).hexdigest()
    ).text.splitlines()
    assert len(lines) == 5
    assert "Forged" not in lines
    assert "Name Forged" in lines[2]


def test_csv_row_limit_is_reported_without_reading_the_whole_table(tmp_path) -> None:
    registry = tmp_path / "long.csv"
    registry.write_text(
        "Item\n" + "".join(f"row-{index}\n" for index in range(2005)),
        encoding="utf-8",
    )
    rendering = read_structured(
        registry, expected_sha256=hashlib.sha256(registry.read_bytes()).hexdigest()
    )
    assert rendering.row_count == 2000
    assert any("beyond the ceiling" in note for note in rendering.notes)


def test_structured_reader_rejects_a_byte_size_over_its_declared_cap(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tmp_path / "large.csv"
    registry.write_text("Item\n" + "x" * 120 + "\n", encoding="utf-8")
    monkeypatch.setattr(structured_sources, "MAX_STRUCTURED_SOURCE_BYTES", 100, raising=False)
    with pytest.raises(structured_sources.BoundStructuredSourceError, match="source_byte_limit"):
        read_structured(
            registry, expected_sha256=hashlib.sha256(registry.read_bytes()).hexdigest()
        )


def test_structured_csv_is_bound_to_the_inventoried_bytes(tmp_path) -> None:
    registry = tmp_path / "abos.csv"
    registry.write_text("Dienst;Betrag\nBeispiel;17,99\n", encoding="utf-8")
    digest = hashlib.sha256(registry.read_bytes()).hexdigest()
    assert "Beispiel" in read_structured(registry, expected_sha256=digest).text
    registry.write_text("Dienst;Betrag\nFremd;999\n", encoding="utf-8")
    with pytest.raises(SourceHashMismatch, match="source_hash_mismatch"):
        read_structured(registry, expected_sha256=digest)


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


def test_xlsx_cell_outside_column_ceiling_is_refused_before_grid_allocation(
    tmp_path,
) -> None:
    book = tmp_path / "wide.xlsx"
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1"><c r="BT1" t="inlineStr">'
        '<is><t>far away</t></is></c></row></sheetData></worksheet>'
    )
    with zipfile.ZipFile(book, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    with pytest.raises(StructuredSourceError, match="column ceiling"):
        read_xlsx(book)


def test_xlsx_reader_binds_cells_to_the_inventoried_bytes(tmp_path) -> None:
    book = _shared_string_workbook(
        tmp_path / "register.xlsx", (("Police",), ("KV-2026-0447",))
    )
    digest = hashlib.sha256(book.read_bytes()).hexdigest()
    assert "KV-2026-0447" in read_structured(book, expected_sha256=digest).text
    with book.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(SourceHashMismatch, match="source_hash_mismatch"):
        read_structured(book, expected_sha256=digest)


def test_xlsx_row_limit_is_reported_as_an_omission(tmp_path) -> None:
    book = _shared_string_workbook(
        tmp_path / "long-register.xlsx",
        (("Item",), ("first",), ("second",), ("third",)),
    )
    rendering = read_xlsx(book, max_rows=2)
    assert rendering.row_count == 2
    assert any("beyond the ceiling" in note for note in rendering.notes)


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


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({"source_tables": "rezepte"}, "source_tables must be a list"),
        ({"source_tables": ["rezepte", "rezepte"]}, "source_tables must not repeat"),
        ({"source_tables": ["table;drop"]}, "source_tables contains"),
        ({"structured_sources": "true"}, "structured_sources must be a boolean"),
    ],
)
def test_structured_source_settings_are_typed_in_the_strict_job_contract(
    tmp_path, parameters, message
) -> None:
    from nemofold.job_io import JobFileError

    with pytest.raises(JobFileError, match=message):
        parse_job_payload(
            {
                "schema": "nemofold.job.v1",
                "workflow": "corpus_query",
                "input_roots": [str(tmp_path)],
                "output_dir": str(tmp_path / "out"),
                "privacy_mode": "local_only",
                "action_mode": "dry_run",
                "parameters": {"terms": ["Beispirol"], **parameters},
            },
            base_dir=tmp_path,
        )


def test_truncated_sqlite_cell_is_explicit_in_reader_and_run_report(tmp_path) -> None:
    database = tmp_path / "medical.sqlite"
    long_finding = "Schilddrüse " + ("x" * 350)
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE bericht ("Befund" TEXT)')
        connection.execute('INSERT INTO bericht VALUES (?)', (long_finding,))
    rendering = read_structured(database, tables=("bericht",))
    assert long_finding not in rendering.text
    assert any("cell" in note and "300" in note and "row 1" in note
               for note in rendering.notes)

    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "corpus_query",
            "input_roots": [str(database)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "terms": ["Schilddrüse"],
                "source_tables": ["bericht"],
                "formats": ["md"],
            },
        },
        base_dir=tmp_path,
    )
    outcome = run_job(
        job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="truncated_cell"
    )
    assert outcome.report.status is RunStatus.EXECUTED
    assert any("cell" in note and "300" in note and "row 1" in note
               for notes in outcome.report.metadata["source_read_notes"].values()
               for note in notes)


def test_truncated_cell_notes_name_the_sqlite_table(tmp_path) -> None:
    database = tmp_path / "two-tables.sqlite"
    with sqlite3.connect(database) as connection:
        for name in ("bericht_a", "bericht_b"):
            connection.execute(f'CREATE TABLE "{name}" ("Befund" TEXT)')
            connection.execute(f'INSERT INTO "{name}" VALUES (?)', ("x" * 350,))
    rendering = read_structured(database, tables=("bericht_a", "bericht_b"))
    truncated = [note for note in rendering.notes if "cell(s)" in note]

    assert len(truncated) == 2
    assert any("Tabelle bericht_a" in note for note in truncated)
    assert any("Tabelle bericht_b" in note for note in truncated)


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


def test_xlsx_omissions_reach_the_persisted_job_report(tmp_path) -> None:
    import json

    from nemofold.delivery import workbook_bytes

    source = tmp_path / "long-register.xlsx"
    source.write_bytes(
        workbook_bytes(("Item",), (("Beispiel",),) * 2003)
    )
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "corpus_query",
            "input_roots": [str(source)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {"terms": ["missing-term"], "formats": ["md"]},
        },
        base_dir=tmp_path,
    )
    result = run_job(
        job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="xlsx_omission"
    )

    assert result.report.status is RunStatus.EXECUTED
    notes_by_source = result.report.metadata["source_read_notes"]
    assert len(notes_by_source) == 1
    assert any(
        "3 row(s) beyond the ceiling of 2000" in note
        for notes in notes_by_source.values()
        for note in notes
    )
    persisted = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert persisted["metadata"]["source_read_notes"] == notes_by_source


def test_declared_missing_sqlite_table_is_visible_in_job_report(tmp_path) -> None:
    database = _mediplaner(tmp_path)
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "corpus_query",
            "input_roots": [str(database)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "terms": ["Beispirol"],
                "source_tables": ["rezepte", "abrechnungen"],
                "formats": ["md"],
            },
        },
        base_dir=tmp_path,
    )
    result = run_job(
        job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="missing_table"
    )

    assert result.report.status is RunStatus.EXECUTED
    assert any(
        "abrechnungen" in note and "not present" in note
        for notes in result.report.metadata["source_read_notes"].values()
        for note in notes
    )


def test_evidence_preview_shows_structured_omissions_before_run(tmp_path) -> None:
    from nemofold.delivery import workbook_bytes

    source = tmp_path / "long-preview.xlsx"
    source.write_bytes(workbook_bytes(("Item",), (("Beispiel",),) * 2001))
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "evidence_analyst",
            "input_roots": [str(source)],
            "output_dir": str(tmp_path / "out"),
            "questions": ["Welcher Eintrag?"],
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {"formats": ["md"]},
        },
        base_dir=tmp_path,
    )
    result = preview_job(
        job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="preview_omission"
    )

    assert result.report.status is RunStatus.PLANNED
    assert any(
        "beyond the ceiling of 2000" in note
        for notes in result.report.metadata["source_read_notes"].values()
        for note in notes
    )


@pytest.mark.parametrize("preview", [True, False])
def test_evidence_respects_declared_tables_in_preview_and_run(tmp_path, preview) -> None:
    database = _mediplaner(tmp_path)
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "evidence_analyst",
            "input_roots": [str(database)],
            "output_dir": str(tmp_path / "out"),
            "questions": ["Welches Präparat?"],
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "source_tables": ["rezepte", "abrechnungen"],
                "formats": ["md"],
            },
        },
        base_dir=tmp_path,
    )
    command = preview_job if preview else run_job
    result = command(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="evidence_table_preview" if preview else "evidence_table_run",
    )

    assert result.report.status is (RunStatus.PLANNED if preview else RunStatus.EXECUTED)
    assert any(
        "abrechnungen" in note and "not present" in note
        for notes in result.report.metadata["source_read_notes"].values()
        for note in notes
    )


def test_a_live_wal_stops_the_corpus_job_instead_of_omitting_the_database(tmp_path) -> None:
    database = _mediplaner(tmp_path)
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO notizen VALUES (2, 'Aktuell nur im WAL')")
        connection.commit()
        assert Path(str(database) + "-wal").exists()
        job = parse_job_payload(
            {
                "schema": "nemofold.job.v1",
                "workflow": "corpus_query",
                "input_roots": [str(database)],
                "output_dir": str(tmp_path / "out"),
                "privacy_mode": "local_only",
                "action_mode": "dry_run",
                "parameters": {"terms": ["Beispirol"]},
            },
            base_dir=tmp_path,
        )
        result = run_job(
            job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="wal_block"
        )
        assert result.report.status is RunStatus.FAILED
        assert "sqlite_sidecar_unbound" in result.report.errors[0]
        assert not (tmp_path / "out" / "wal_block.corpus-query.json").exists()
    finally:
        connection.close()


def test_missing_sqlite_deserialize_stops_job_instead_of_dropping_source(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _mediplaner(tmp_path)
    original_connect = sqlite3.connect

    class NoDeserializeConnection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            if name == "deserialize":
                raise AttributeError(name)
            return getattr(self.connection, name)

    def without_deserialize(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        return NoDeserializeConnection(connection) if args[0] == ":memory:" else connection

    monkeypatch.setattr(structured_sources.sqlite3, "connect", without_deserialize)
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "corpus_query",
            "input_roots": [str(database)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {"terms": ["Beispirol"]},
        },
        base_dir=tmp_path,
    )
    result = run_job(
        job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="no_deserialize"
    )
    assert result.report.status is RunStatus.FAILED
    assert "sqlite_deserialize_unavailable" in result.report.errors[0]
    assert not (tmp_path / "out" / "no_deserialize.corpus-query.json").exists()


def test_temporary_xlsx_change_during_corpus_read_cannot_enter_claims(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nemofold.delivery import workbook_bytes

    source = tmp_path / "register.xlsx"
    source.write_bytes(workbook_bytes(("Dienst",), (("Beispiel",),)))
    original_bytes = source.read_bytes()
    original_read = application.read_structured

    def change_only_while_reading(path, **kwargs):
        if Path(path).resolve() != source.resolve():
            return original_read(path, **kwargs)
        source.write_bytes(workbook_bytes(("Dienst",), (("Fremd",),)))
        try:
            return original_read(path, **kwargs)
        finally:
            source.write_bytes(original_bytes)

    monkeypatch.setattr(application, "read_structured", change_only_while_reading)
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "corpus_query",
            "input_roots": [str(source)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {"terms": ["Dienst"], "formats": ["md"]},
        },
        base_dir=tmp_path,
    )
    result = run_job(
        job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="xlsx_race"
    )

    assert result.report.status is RunStatus.FAILED
    assert "source_hash_mismatch" in result.report.errors[0]
    assert not (tmp_path / "out" / "xlsx_race.corpus-query.json").exists()
