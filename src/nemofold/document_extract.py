from __future__ import annotations

import json
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

PLAIN_TEXT_SUFFIXES = frozenset(
    {".csv", ".json", ".log", ".md", ".rst", ".toml", ".txt", ".xml", ".yaml", ".yml"}
)


MAX_XML_MEMBER_BYTES = 32 * 1024 * 1024


def read_xml_member(archive: zipfile.ZipFile, name: str) -> bytes:
    """Read one XML part of an office archive under two explicit limits.

    Documents in an approved root are untrusted input - that is the whole point
    of approving a root rather than trusting a folder - so a container format
    gets both defences the format invites. A member that inflates beyond the
    ceiling is refused before it is decompressed, and any document type
    declaration is refused outright: a legitimate OOXML or ODF part has none,
    while an entity declaration is how a small file becomes an out-of-memory
    condition on somebody's laptop.
    """
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise ValueError(f"archive part missing: {name}") from exc
    if info.file_size > MAX_XML_MEMBER_BYTES:
        raise ValueError(
            f"archive part {name} declares {info.file_size} bytes, beyond the "
            f"{MAX_XML_MEMBER_BYTES} byte ceiling"
        )
    data = archive.read(name)
    if b"<!DOCTYPE" in data[:8192] or b"<!ENTITY" in data:
        raise ValueError(f"archive part {name} carries a document type declaration")
    return data


class UnsupportedDocumentError(ValueError):
    """Raised when no local extractor is available for a document."""


class _VisibleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _xml_paragraphs(data: bytes, *, paragraph_names: frozenset[str]) -> str:
    root = ElementTree.fromstring(data)
    paragraphs: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] not in paragraph_names:
            continue
        text = "".join(element.itertext()).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def _extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            data = read_xml_member(archive, "word/document.xml")
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"invalid DOCX document: {path.name}") from exc
    return _xml_paragraphs(data, paragraph_names=frozenset({"p"}))


def _extract_odt(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            data = read_xml_member(archive, "content.xml")
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"invalid ODT document: {path.name}") from exc
    return _xml_paragraphs(data, paragraph_names=frozenset({"h", "p"}))


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - packaging guarantees the dependency
        raise UnsupportedDocumentError("PDF extraction requires pypdf") from exc
    try:
        reader = PdfReader(path)
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:
        raise ValueError(f"invalid or encrypted PDF document: {path.name}") from exc
    return "\f".join(pages)


def extract_document_text(path: str | Path, *, mime_type: str = "") -> str:
    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix in PLAIN_TEXT_SUFFIXES or mime_type.startswith("text/"):
        text = source.read_text(encoding="utf-8-sig")
        if suffix == ".json":
            json.loads(text)
        return text
    if suffix in {".html", ".htm"}:
        parser = _VisibleHTML()
        parser.feed(source.read_text(encoding="utf-8-sig"))
        return "\n".join(parser.parts)
    if suffix == ".docx":
        return _extract_docx(source)
    if suffix == ".odt":
        return _extract_odt(source)
    if suffix == ".pdf":
        return _extract_pdf(source)
    raise UnsupportedDocumentError(f"unsupported document type: {suffix or '<none>'}")
