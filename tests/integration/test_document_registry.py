from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.document_registry import (
    COLUMN_TEMPLATES,
    RegistryColumn,
    build_registry,
    columns_from_parameters,
    due_within,
    registry_to_csv,
)
from nemofold.job_io import parse_job_payload

MEDICAL_REPORT = """Arztbericht
Patient: Lukas Geiger
Fachrichtung: Kardiologie
Arzt: Dr. Anna Weber
Kontakt: 030 555 1234
Befund: Belastungs-EKG ohne Auffaelligkeiten.
"""

SECOND_REPORT = """Arztbericht
Patient: Lukas Geiger
Fachrichtung: Orthopaedie
Arzt: Dr. Peter Klein
Befund: Meniskus intakt.
"""

INSURANCE = """Versicherungsschein
Police: AKV-99182
Tarif: Auslandsreise Komfort
Abdeckung: Weltweit ausser USA
Kosten: 148,00 EUR pro Jahr
Naechste Faelligkeit: 2026-09-15
Kontakt: service@example.org
"""


def _corpus(tmp_path: Path) -> Path:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "bericht-kardio.txt").write_text(MEDICAL_REPORT, encoding="utf-8")
    (documents / "bericht-ortho.txt").write_text(SECOND_REPORT, encoding="utf-8")
    return documents


def test_registry_anchors_every_filled_cell_and_leaves_gaps_empty() -> None:
    columns = COLUMN_TEMPLATES["medical_reports"]
    table = build_registry(
        (("src_a", "bericht-kardio.txt"), ("src_b", "bericht-ortho.txt")),
        {"src_a": MEDICAL_REPORT, "src_b": SECOND_REPORT},
        columns,
    )

    assert len(table.rows) == 2
    first = {cell.column: cell for cell in table.rows[0].cells}
    assert first["Fachrichtung"].value == "Kardiologie"
    assert first["Fachrichtung"].source_id == "src_a"
    assert first["Fachrichtung"].line == 3
    assert first["Fachrichtung"].quote == "Fachrichtung: Kardiologie"

    # The second report carries no contact line, so that cell stays empty.
    second = {cell.column: cell for cell in table.rows[1].cells}
    assert second["Kontakt"].value is None
    assert second["Kontakt"].source_id is None
    assert second["Kontakt"].filled is False
    assert table.empty_cells == 1


def test_registry_reads_the_insurance_labels_of_the_second_leading_case() -> None:
    table = build_registry(
        (("src_i", "police.txt"),),
        {"src_i": INSURANCE},
        COLUMN_TEMPLATES["insurance_registry"],
    )

    values = {cell.column: cell.value for cell in table.rows[0].cells}
    assert values["Police"] == "AKV-99182"
    assert values["Tarif"] == "Auslandsreise Komfort"
    assert values["Abdeckung"] == "Weltweit ausser USA"
    assert values["Kosten"] == "148,00 EUR pro Jahr"
    assert values["Kontakt"] == "service@example.org"


def test_recurring_costs_template_reports_due_and_unreadable_dates() -> None:
    unreadable = INSURANCE.replace("2026-09-15", "im Herbst")
    table = build_registry(
        (("src_i", "police.txt"), ("src_u", "vage.txt")),
        {"src_i": INSURANCE, "src_u": unreadable},
        COLUMN_TEMPLATES["recurring_costs"],
    )

    entries = due_within(
        table,
        column="Nächste Fälligkeit",
        reference=date(2026, 9, 1),
        days=30,
    )
    states = {item["source_id"]: item for item in entries}
    assert states["src_i"]["state"] == "due"
    assert states["src_i"]["days_until"] == 14
    # A date nobody can parse is reported, never silently dropped.
    assert states["src_u"]["state"] == "unreadable_date"
    assert states["src_u"]["due_date"] is None

    overdue = due_within(
        table, column="Nächste Fälligkeit", reference=date(2026, 10, 1), days=30
    )
    assert next(item for item in overdue if item["source_id"] == "src_i")["state"] == "overdue"


def test_topic_filter_skips_sources_instead_of_inventing_rows() -> None:
    table = build_registry(
        (("src_a", "kardio.txt"), ("src_b", "ortho.txt")),
        {"src_a": MEDICAL_REPORT, "src_b": SECOND_REPORT},
        COLUMN_TEMPLATES["medical_reports"],
        topic_filter=("Kardiologie",),
    )

    assert [row.source_id for row in table.rows] == ["src_a"]
    assert table.skipped_source_ids == ("src_b",)


def test_csv_keeps_the_anchor_next_to_every_value() -> None:
    table = build_registry(
        (("src_a", "kardio.txt"),),
        {"src_a": MEDICAL_REPORT},
        (RegistryColumn("Arzt", aliases=("Physician",)),),
    )

    rows = list(csv.reader(io.StringIO(registry_to_csv(table))))
    assert rows[0] == ["source_id", "display_name", "Arzt", "Arzt [source]"]
    assert rows[1] == ["src_a", "kardio.txt", "Dr. Anna Weber", "src_a:4"]


@pytest.mark.parametrize(
    ("columns", "template", "message"),
    [
        (None, None, "requires columns or a column_template"),
        (None, "unknown_template", "unknown column_template"),
        ([], None, "non-empty list"),
        ([{"name": "A"}, {"name": "a"}], None, "duplicate column"),
        ([{"label": "A"}], None, "each column needs name"),
    ],
)
def test_column_contract_refuses_unusable_declarations(columns, template, message) -> None:
    with pytest.raises(ValueError, match=message):
        columns_from_parameters(columns, template)


def test_document_registry_runs_end_to_end_and_hashes_its_pdf(tmp_path) -> None:
    documents = _corpus(tmp_path)
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "document_registry",
            "input_roots": [str(documents)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "column_template": "medical_reports",
                "formats": ["md", "pdf"],
                "title": "Arztberichte-Verzeichnis",
            },
        },
        base_dir=tmp_path,
    )

    result = run_job(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="registry_e2e",
    )
    report = result.report

    assert report.status is RunStatus.EXECUTED
    assert report.metadata["rows"] == 2
    assert report.metadata["filled_cells"] == 9
    assert report.metadata["empty_cells"] == 1
    assert report.metadata["extraction"] == "labelled_lines_only"

    formats = {artifact.format for artifact in report.artifacts}
    assert {"document-registry", "csv", "pdf", "markdown"} <= formats

    pdf = next(artifact for artifact in report.artifacts if artifact.format == "pdf")
    written = Path(pdf.path)
    assert written.is_file()
    assert written.read_bytes().startswith(b"%PDF-")
    # The ledger hash must match the file that was actually written.
    import hashlib

    assert pdf.sha256 == hashlib.sha256(written.read_bytes()).hexdigest()

    table = json.loads(
        next(
            Path(artifact.path)
            for artifact in report.artifacts
            if artifact.format == "document-registry"
        ).read_text(encoding="utf-8")
    )
    assert table["schema"] == "nemofold.document-registry.v1"
    assert [column["name"] for column in table["columns"]][0] == "Name"
    anchored = [
        cell
        for row in table["rows"]
        for cell in row["cells"]
        if cell["value"] is not None
    ]
    assert anchored and all(cell["source_id"] and cell["line"] for cell in anchored)
