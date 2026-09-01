from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from nemofold.delivery import (
    DeliveryError,
    deliver_artifacts,
    delivery_payload,
    route_for,
    validate_delivery_body,
    workbook_bytes,
    write_print_package,
    write_workbook,
)

# --------------------------------------------------------------------------- #
# A workbook a ledger can hash
# --------------------------------------------------------------------------- #


def test_the_same_table_writes_the_same_bytes_every_time() -> None:
    header = ("Police", "Tarif", "Beitrag")
    rows = (("KV-2026-0447", "Teilkasko", "148"), ("KV-2026-0448", "Vollkasko", "212"))

    first = workbook_bytes(header, rows)
    second = workbook_bytes(header, rows)

    # A spreadsheet library stamps a build time into the archive, which would
    # make the same table hash differently on every run and make the ledger
    # entry meaningless.
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


def test_the_workbook_is_a_real_workbook() -> None:
    openpyxl = pytest.importorskip("openpyxl")

    data = workbook_bytes(("A", "B"), (("1", "2"),))
    book = openpyxl.load_workbook(io.BytesIO(data))

    assert [list(row) for row in book.active.iter_rows(values_only=True)] == [
        ["A", "B"],
        ["1", "2"],
    ]


def test_a_workbook_escapes_what_would_break_the_xml(tmp_path) -> None:
    record = write_workbook(
        tmp_path / "tabelle.xlsx", ("Feld",), (('<b>"&amp;"</b>',),)
    )

    with zipfile.ZipFile(tmp_path / "tabelle.xlsx") as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "&lt;b&gt;" in sheet
    assert record.sha256


@pytest.mark.parametrize(
    ("header", "rows"),
    [(tuple(f"c{index}" for index in range(61)), ()), (("a",), tuple((("x",),) * 20001))],
)
def test_a_sheet_beyond_its_ceiling_is_refused(header, rows) -> None:
    with pytest.raises(DeliveryError, match="may not exceed"):
        workbook_bytes(header, rows)


# --------------------------------------------------------------------------- #
# Delivery rules file things where they belong, and nowhere else
# --------------------------------------------------------------------------- #


def test_a_route_is_found_by_kind_then_by_default() -> None:
    body = validate_delivery_body(
        {
            "routes": [{"artifact_kind": "findings", "target_root": "berichte"}],
            "default_target": "ablage",
        }
    )

    assert route_for("findings", body).target_root == "berichte"
    assert route_for("anything-else", body).target_root == "ablage"
    assert route_for("findings", validate_delivery_body({"routes": []})) is None


def test_an_artifact_is_filed_where_its_rule_says(tmp_path) -> None:
    source = tmp_path / "out" / "bericht.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Bericht", encoding="utf-8")
    target = tmp_path / "ablage"
    body = validate_delivery_body(
        {"routes": [{"artifact_kind": "findings", "target_root": str(target)}]}
    )

    receipts, notes = deliver_artifacts(
        ((str(source), "findings"),),
        body,
        allowed_roots=(str(tmp_path),),
        apply_actions=True,
    )

    assert receipts[0].delivered is True
    assert (target / "bericht.md").read_text(encoding="utf-8") == "# Bericht"
    assert notes == ()
    assert delivery_payload(receipts, notes)["delivered_count"] == 1


def test_a_target_outside_the_approved_roots_is_refused_not_created(tmp_path) -> None:
    source = tmp_path / "bericht.md"
    source.write_text("# Bericht", encoding="utf-8")
    outside = tmp_path.parent / "woanders"
    body = validate_delivery_body(
        {"routes": [{"artifact_kind": "findings", "target_root": str(outside)}]}
    )

    receipts, notes = deliver_artifacts(
        ((str(source), "findings"),),
        body,
        allowed_roots=(str(tmp_path),),
        apply_actions=True,
    )

    # A convenience must not become a way around the one boundary everything
    # else respects.
    assert receipts[0].delivered is False
    assert "outside the approved roots" in receipts[0].reason
    assert not outside.exists()
    assert "approve that root first" in notes[0]


def test_without_the_action_gate_nothing_is_copied(tmp_path) -> None:
    source = tmp_path / "bericht.md"
    source.write_text("# Bericht", encoding="utf-8")
    target = tmp_path / "ablage"
    body = validate_delivery_body(
        {"routes": [{"artifact_kind": "findings", "target_root": str(target)}]}
    )

    receipts, _ = deliver_artifacts(
        ((str(source), "findings"),),
        body,
        allowed_roots=(str(tmp_path),),
        apply_actions=False,
    )

    assert receipts[0].delivered is False
    assert "preview only" in receipts[0].reason
    assert not target.exists()


def test_an_artifact_no_rule_matches_is_reported(tmp_path) -> None:
    source = tmp_path / "x.md"
    source.write_text("x", encoding="utf-8")

    receipts, _ = deliver_artifacts(
        ((str(source), "unbekannt"),),
        validate_delivery_body({"routes": []}),
        allowed_roots=(str(tmp_path),),
        apply_actions=True,
    )

    assert receipts[0].delivered is False
    assert receipts[0].reason == "no rule matches this kind"


# --------------------------------------------------------------------------- #
# Print-ready, and honest about it
# --------------------------------------------------------------------------- #


def test_printing_prepares_a_file_and_says_it_did_not_print(tmp_path) -> None:
    record, metadata = write_print_package(tmp_path, "run_1", str(tmp_path / "bericht.pdf"))

    note = Path(record.path).read_text(encoding="utf-8")
    assert metadata["printed"] is False
    assert "Start-Process" in note
    assert "-Verb Print" in note
    # The reason is in the file a person reads, not only in a design document.
    assert "no receipt, no page count" in note
    assert "returns nothing this run could put in a receipt" in metadata["print_note"]
