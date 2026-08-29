from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .contracts import SourceRecord

HASH_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class InventoryResult:
    root: str
    records: tuple[SourceRecord, ...]
    new_source_ids: tuple[str, ...]
    changed_source_ids: tuple[str, ...]
    unchanged_source_ids: tuple[str, ...]
    deleted_source_ids: tuple[str, ...]

    def hashes_by_source_id(self) -> dict[str, str]:
        return {record.source_id: record.sha256 for record in self.records}


def _stable_source_id(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").casefold().encode("utf-8")
    return f"src_{hashlib.sha256(normalized).hexdigest()[:16]}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def scan_root(
    root: str | Path,
    *,
    previous_hashes: Mapping[str, str] | None = None,
) -> InventoryResult:
    resolved_root = Path(root).resolve()
    if not resolved_root.is_dir():
        raise NotADirectoryError(resolved_root)

    previous = dict(previous_hashes or {})
    records: list[SourceRecord] = []
    new_ids: list[str] = []
    changed_ids: list[str] = []
    unchanged_ids: list[str] = []

    candidates = sorted(
        (path for path in resolved_root.rglob("*") if not path.is_dir()),
        key=lambda path: path.relative_to(resolved_root).as_posix().casefold(),
    )
    for path in candidates:
        display_name = path.relative_to(resolved_root).as_posix()
        source_id = _stable_source_id(display_name)
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.is_symlink():
            digest = ""
            status = "excluded_symlink"
        else:
            try:
                digest = _sha256_file(path)
            except (OSError, PermissionError):
                digest = ""
                status = "unreadable"
            else:
                old_digest = previous.get(source_id)
                if old_digest is None:
                    status = "new"
                    new_ids.append(source_id)
                elif old_digest == digest:
                    status = "unchanged"
                    unchanged_ids.append(source_id)
                else:
                    status = "changed"
                    changed_ids.append(source_id)

        if status in {"unreadable", "excluded_symlink"}:
            if source_id not in previous:
                new_ids.append(source_id)
            elif previous[source_id] == digest:
                unchanged_ids.append(source_id)
            else:
                changed_ids.append(source_id)

        records.append(
            SourceRecord(
                source_id=source_id,
                path=str(path),
                display_name=display_name,
                sha256=digest,
                mime_type=mime_type,
                extraction_status=status,
            )
        )

    current_ids = {record.source_id for record in records}
    return InventoryResult(
        root=str(resolved_root),
        records=tuple(records),
        new_source_ids=tuple(new_ids),
        changed_source_ids=tuple(changed_ids),
        unchanged_source_ids=tuple(unchanged_ids),
        deleted_source_ids=tuple(sorted(set(previous) - current_ids)),
    )
