from __future__ import annotations

import io
import re
import textwrap
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from .artifacts import (
    render_markdown,
    render_text,
    write_binary_artifact,
    write_text_artifact,
)
from .contracts import ArtifactRecord, Claim, Coverage

SUPPORTED_FORMATS = frozenset({"md", "txt", "pdf", "docx", "odt"})


@dataclass(frozen=True, slots=True)
class ReportDocument:
    title: str
    claims: tuple[Claim, ...]
    coverage: Coverage
    source_labels: tuple[tuple[str, str], ...] = ()


def _zip_info(name: str, *, stored: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o644 << 16
    return info


def _xml_paragraphs(text: str, *, prefix: str) -> str:
    return "".join(f"<{prefix}:p>{escape(line)}</{prefix}:p>" for line in text.splitlines())


def _render_docx(text: str) -> bytes:
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(
            f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(line)}</w:t></w:r></w:p>"
            for line in text.splitlines()
        )
        + "<w:sectPr/></w:body></w:document>"
    ).encode()
    content_types = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Default Extension="rels" '
        b'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        b'<Default Extension="xml" ContentType="application/xml"/>'
        b'<Override PartName="/word/document.xml" '
        b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        b"</Types>"
    )
    relationships = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rId1" '
        b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        b'officeDocument" '
        b'Target="word/document.xml"/>'
        b"</Relationships>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(_zip_info("[Content_Types].xml"), content_types)
        archive.writestr(_zip_info("_rels/.rels"), relationships)
        archive.writestr(_zip_info("word/document.xml"), document_xml)
    return output.getvalue()


def _render_odt(text: str) -> bytes:
    mimetype = b"application/vnd.oasis.opendocument.text"
    content_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'office:version="1.2"><office:body><office:text>'
        + _xml_paragraphs(text, prefix="text")
        + "</office:text></office:body></office:document-content>"
    ).encode()
    manifest_xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<manifest:manifest '
        b'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
        b'manifest:version="1.2">'
        b'<manifest:file-entry manifest:full-path="/" '
        b'manifest:media-type="application/vnd.oasis.opendocument.text"/>'
        b'<manifest:file-entry manifest:full-path="content.xml" '
        b'manifest:media-type="text/xml"/>'
        b"</manifest:manifest>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(_zip_info("mimetype", stored=True), mimetype)
        archive.writestr(_zip_info("content.xml"), content_xml)
        archive.writestr(_zip_info("META-INF/manifest.xml"), manifest_xml)
    return output.getvalue()


def _pdf_escape(line: str) -> bytes:
    escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return escaped.encode("cp1252", errors="replace")


def _render_pdf(text: str) -> bytes:
    lines: list[str] = []
    for line in text.splitlines():
        lines.extend(
            textwrap.wrap(line, width=110, break_long_words=True, break_on_hyphens=False)
            or [""]
        )
    pages = [lines[index : index + 68] for index in range(0, len(lines), 68)] or [[]]
    page_object_ids = [4 + index * 2 for index in range(len(pages))]
    kids = " ".join(f"{object_id} 0 R" for object_id in page_object_ids)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
    ]
    for index, page_lines in enumerate(pages):
        page_object_id = page_object_ids[index]
        content_object_id = page_object_id + 1
        commands = [b"BT", b"/F1 9 Tf", b"50 790 Td", b"11 TL"]
        for line in page_lines:
            commands.append(b"(" + _pdf_escape(line) + b") Tj")
            commands.append(b"T*")
        commands.append(b"ET")
        stream = b"\n".join(commands) + b"\n"
        objects.extend(
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                b"/Resources << /Font << /F1 3 0 R >> >> /Contents "
                + f"{content_object_id} 0 R >>".encode(),
                f"<< /Length {len(stream)} >>\nstream\n".encode()
                + stream
                + b"endstream",
            )
        )
    result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode())
        result.extend(body)
        result.extend(b"\nendobj\n")
    xref_offset = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    result.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(result)


def render_report_formats(
    document: ReportDocument,
    output_dir: str | Path,
    *,
    basename: str = "report",
    formats: tuple[str, ...] = ("md", "txt", "pdf", "docx", "odt"),
) -> tuple[ArtifactRecord, ...]:
    normalized = tuple(item.casefold() for item in formats)
    unsupported = sorted(set(normalized) - SUPPORTED_FORMATS)
    if unsupported:
        raise ValueError(f"unsupported report formats: {', '.join(unsupported)}")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", basename):
        raise ValueError("basename must contain only letters, numbers, underscores, or hyphens")
    output = Path(output_dir)
    markdown = render_markdown(document.title, document.claims, document.coverage)
    plain = render_text(document.title, document.claims, document.coverage)
    if document.source_labels:
        markdown += "\n## Source catalog\n\n" + "\n".join(
            f"- {source_id}: {display_name}"
            for source_id, display_name in document.source_labels
        )
        markdown += "\n"
        plain += "\nSource catalog\n" + "\n".join(
            f"  {source_id}: {display_name}"
            for source_id, display_name in document.source_labels
        )
        plain += "\n"
    records: list[ArtifactRecord] = []
    for format_name in normalized:
        if format_name == "md":
            records.append(write_text_artifact(output / f"{basename}.md", markdown, "markdown"))
        elif format_name == "txt":
            records.append(write_text_artifact(output / f"{basename}.txt", plain, "text"))
        elif format_name == "pdf":
            records.append(
                write_binary_artifact(output / f"{basename}.pdf", _render_pdf(plain), "pdf")
            )
        elif format_name == "docx":
            records.append(
                write_binary_artifact(output / f"{basename}.docx", _render_docx(plain), "docx")
            )
        elif format_name == "odt":
            records.append(
                write_binary_artifact(output / f"{basename}.odt", _render_odt(plain), "odt")
            )
    return tuple(records)
