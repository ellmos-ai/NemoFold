"""K9/K10/K11: filing an artifact, exporting a table, and getting it printed.

Three small capabilities that share one idea: a produced file is not finished
until it is somewhere a person will look. Filing is therefore a real, journalled
action under the same allow roots as everything else, not a convenience.

Printing is deliberately not one of them. Windows can hand a file to whatever
program is registered for its type through the shell print verb, and that call
tells the caller nothing: no receipt, no page count, no way to know whether a
printer existed, and no way to undo it. An action this product cannot describe
afterwards is an action it should not claim to have taken - so print_action
produces a print-ready file plus the exact instruction to print it, and says
that the printing itself is the person's step. That is a smaller promise, and it
is one that holds.

The workbook writer here is hand-rolled on zipfile for one reason: a run ledger
hashes what it writes, and the usual spreadsheet libraries stamp a build time
into the archive, which would make the same table hash differently every run.
Every entry below is written with a fixed timestamp.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .artifacts import write_binary_artifact, write_text_artifact
from .contracts import ArtifactRecord
from .policy import PolicyConfig, PolicyGate

DELIVERY_SCHEMA = "nemofold.delivery.v1"
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
MAX_ROUTES = 40
MAX_SHEET_ROWS = 20000
MAX_SHEET_COLUMNS = 60


class DeliveryError(ValueError):
    """Raised when a delivery cannot be carried out under the declared rules."""


# --------------------------------------------------------------------------- #
# A deterministic workbook
# --------------------------------------------------------------------------- #


def _column_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def workbook_bytes(
    header: tuple[str, ...], rows: tuple[tuple[str, ...], ...], *, sheet_name: str = "Tabelle"
) -> bytes:
    """Write a minimal, valid, byte-stable XLSX.

    Values are written as inline strings, which keeps the file free of a shared
    string table whose ordering would be one more thing to keep deterministic.
    """
    if len(header) > MAX_SHEET_COLUMNS:
        raise DeliveryError(f"a sheet may not exceed {MAX_SHEET_COLUMNS} columns")
    if len(rows) > MAX_SHEET_ROWS:
        raise DeliveryError(f"a sheet may not exceed {MAX_SHEET_ROWS} rows")

    def cell(column: int, row: int, value: str) -> str:
        reference = f"{_column_name(column)}{row}"
        return (
            f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">'
            f"{escape(str(value))}</t></is></c>"
        )

    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        "<sheetData>",
    ]
    lines.append(
        "<row r=\"1\">"
        + "".join(cell(index, 1, value) for index, value in enumerate(header))
        + "</row>"
    )
    for number, row in enumerate(rows, start=2):
        lines.append(
            f'<row r="{number}">'
            + "".join(
                cell(index, number, value)
                for index, value in enumerate(row[:MAX_SHEET_COLUMNS])
            )
            + "</row>"
        )
    lines.extend(["</sheetData>", "</worksheet>"])
    sheet = "".join(lines)

    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package'
            '.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd'
            '.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd'
            '.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            'relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats'
            '.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"'
            "/></Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{escape(sheet_name[:31])}" sheetId="1" r:id="rId1"/>'
            "</sheets></workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            'relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats'
            '.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"'
            "/></Relationships>"
        ),
        "xl/worksheets/sheet1.xml": sheet,
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(parts):
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, parts[name])
    return stream.getvalue()


def write_workbook(
    path: Path, header: tuple[str, ...], rows: tuple[tuple[str, ...], ...]
) -> ArtifactRecord:
    """Write the workbook through the same atomic path as every other artifact."""
    return write_binary_artifact(path, workbook_bytes(header, rows), "table-workbook")


# --------------------------------------------------------------------------- #
# Delivery rules
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class DeliveryRoute:
    """Where one kind of artifact belongs, and in which shape."""

    artifact_kind: str
    target_root: str
    file_format: str = "as-is"


def validate_delivery_body(value: Any) -> dict[str, object]:
    """Check a delivery_rules policy body: kinds routed to declared folders."""
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {"routes", "default_target"}:
        raise DeliveryError("a delivery_rules body may only carry routes and default_target")
    raw = value.get("routes", [])
    if not isinstance(raw, list) or len(raw) > MAX_ROUTES:
        raise DeliveryError(f"routes must be a list of at most {MAX_ROUTES} entries")
    routes: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) - {
            "artifact_kind", "target_root", "file_format"
        }:
            raise DeliveryError(
                "a route holds only artifact_kind, target_root and file_format"
            )
        kind = str(item.get("artifact_kind", "")).strip()
        target = str(item.get("target_root", "")).strip()
        if not kind or not target:
            raise DeliveryError("a route needs an artifact_kind and a target_root")
        routes.append(
            {
                "artifact_kind": kind,
                "target_root": target,
                "file_format": str(item.get("file_format", "as-is")).strip() or "as-is",
            }
        )
    default_target = str(value.get("default_target", "")).strip()
    return {"routes": routes, "default_target": default_target}


def route_for(kind: str, body: dict[str, object]) -> DeliveryRoute | None:
    """Find the route for an artifact kind, or the declared default."""
    routes = body.get("routes") or []
    assert isinstance(routes, list)
    for item in routes:
        if str(item.get("artifact_kind")) == kind:
            return DeliveryRoute(
                artifact_kind=kind,
                target_root=str(item["target_root"]),
                file_format=str(item.get("file_format", "as-is")),
            )
    default_target = body.get("default_target")
    if default_target:
        return DeliveryRoute(artifact_kind=kind, target_root=str(default_target))
    return None


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """What was filed where, or precisely why it was not."""

    source_path: str
    target_path: str | None
    artifact_kind: str
    delivered: bool
    reason: str


def deliver_artifacts(
    artifacts: tuple[tuple[str, str], ...],
    body: dict[str, object],
    *,
    allowed_roots: tuple[str, ...],
    apply_actions: bool,
) -> tuple[tuple[DeliveryReceipt, ...], tuple[str, ...]]:
    """File each artifact where its rule says, under the same allow roots.

    A target outside the approved roots is refused rather than created: a
    delivery rule is a convenience, and a convenience must not be a way around
    the one boundary everything else respects. Without the apply gate nothing is
    copied, and the receipt says the run was a preview.
    """
    gate = PolicyGate(PolicyConfig(allowed_roots=allowed_roots))
    receipts: list[DeliveryReceipt] = []
    notes: list[str] = []
    for path_value, kind in artifacts:
        route = route_for(kind, body)
        if route is None:
            receipts.append(
                DeliveryReceipt(path_value, None, kind, False, "no rule matches this kind")
            )
            continue
        if not gate.path_allowed(route.target_root):
            receipts.append(
                DeliveryReceipt(
                    path_value,
                    None,
                    kind,
                    False,
                    f"target {route.target_root} is outside the approved roots",
                )
            )
            notes.append(
                f"delivery rule for {kind} points outside the approved roots and was "
                "refused; approve that root first."
            )
            continue
        source = Path(path_value)
        target = Path(route.target_root) / source.name
        if not apply_actions:
            receipts.append(
                DeliveryReceipt(
                    path_value, str(target), kind, False,
                    "preview only: the server was started without the file-action gate",
                )
            )
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        except OSError as exc:
            receipts.append(DeliveryReceipt(path_value, str(target), kind, False, str(exc)))
            continue
        receipts.append(DeliveryReceipt(path_value, str(target), kind, True, "filed"))
    return tuple(receipts), tuple(notes)


def delivery_payload(
    receipts: tuple[DeliveryReceipt, ...], notes: tuple[str, ...]
) -> dict[str, object]:
    return {
        "schema": DELIVERY_SCHEMA,
        "delivered_count": sum(1 for item in receipts if item.delivered),
        "receipts": [
            {
                "source_path": item.source_path,
                "target_path": item.target_path,
                "artifact_kind": item.artifact_kind,
                "delivered": item.delivered,
                "reason": item.reason,
            }
            for item in receipts
        ],
        "notes": list(notes),
        "boundary_note": (
            "A delivery target is checked against the same approved roots as every "
            "other write. A rule cannot file something somewhere the run may not go."
        ),
    }


# --------------------------------------------------------------------------- #
# Print-ready, rather than printed
# --------------------------------------------------------------------------- #

PRINT_INSTRUCTIONS = """# Print-ready output

NemoFold prepared the file below and did not print it.

    {path}

To print it, open it and use your usual print dialogue, or from PowerShell:

    Start-Process -FilePath "{path}" -Verb Print

## Why this is not done for you

Handing a file to whatever program is registered for its type tells this program
nothing back: no receipt, no page count, no way to know a printer existed, and
no way to undo it. Every other action here can be described afterwards and
reversed or refused. Printing cannot, so it stays your step - and this file is
the whole of what NemoFold would have run.
"""


def write_print_package(
    output: Path, run_id: str, artifact_path: str
) -> tuple[ArtifactRecord, dict[str, object]]:
    """Write the instruction sheet next to the file a person will print."""
    note = write_text_artifact(
        output / f"{run_id}.print-instructions.md",
        PRINT_INSTRUCTIONS.format(path=artifact_path),
        "print-instructions",
    )
    metadata: dict[str, object] = {
        "printed": False,
        "print_ready_path": artifact_path,
        "print_note": (
            "NemoFold prepares a print-ready file and the exact command. It does not "
            "invoke the printer, because that call returns nothing this run could put "
            "in a receipt."
        ),
        "prepared_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    return note, metadata


def write_delivery_report(
    output: Path, run_id: str, payload: dict[str, object]
) -> ArtifactRecord:
    return write_text_artifact(
        output / f"{run_id}.delivery.json",
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "delivery-receipt",
    )
