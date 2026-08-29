from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .contracts import SourceRecord


@dataclass(frozen=True, slots=True)
class BundleResult:
    bundle_path: Path
    manifest_path: Path
    zip_path: Path
    bundle_sha256: str
    manifest_sha256: str


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o644 << 16
    return info


def create_text_bundle(
    records: Sequence[SourceRecord],
    source_texts: Mapping[str, str],
    output_dir: str | Path,
    *,
    bundle_name: str = "document_bundle",
) -> BundleResult:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", bundle_name):
        raise ValueError("bundle_name must contain only letters, numbers, underscores, or hyphens")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda item: item.display_name.casefold())
    bundle_parts: list[str] = []
    entries: list[dict[str, object]] = []
    included = 0

    for record in ordered:
        text = source_texts.get(record.source_id)
        reason = None
        if record.extraction_status in {"unreadable", "excluded_symlink"}:
            reason = record.extraction_status
        elif text is None:
            reason = "missing_text"
        if reason is None:
            included += 1
            bundle_parts.extend(
                (
                    f"[SOURCE {record.source_id} | {record.display_name}]",
                    text or "",
                    f"[/SOURCE {record.source_id}]",
                    "",
                )
            )
        entries.append(
            {
                "source_id": record.source_id,
                "display_name": record.display_name,
                "sha256": record.sha256,
                "status": record.extraction_status,
                "included": reason is None,
                "reason": reason,
            }
        )

    bundle_bytes = "\n".join(bundle_parts).encode("utf-8")
    manifest = {
        "schema": "nemofold.bundle-manifest.v1",
        "bundle": f"{bundle_name}.txt",
        "coverage": {
            "total": len(entries),
            "included": included,
            "excluded": len(entries) - included,
        },
        "entries": entries,
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    bundle_path = output / f"{bundle_name}.txt"
    manifest_path = output / f"{bundle_name}.manifest.json"
    zip_path = output / f"{bundle_name}.zip"
    _atomic_bytes(bundle_path, bundle_bytes)
    _atomic_bytes(manifest_path, manifest_bytes)

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr(_zip_info(bundle_path.name), bundle_bytes)
        archive.writestr(_zip_info(manifest_path.name), manifest_bytes)
    _atomic_bytes(zip_path, archive_buffer.getvalue())

    return BundleResult(
        bundle_path=bundle_path,
        manifest_path=manifest_path,
        zip_path=zip_path,
        bundle_sha256=hashlib.sha256(bundle_bytes).hexdigest(),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )
