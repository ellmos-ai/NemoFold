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
    roots: tuple[str, ...] = ()

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

    candidates = tuple(
        (
            path,
            path.relative_to(resolved_root).as_posix(),
            path.relative_to(resolved_root).as_posix(),
        )
        for path in sorted(
            (path for path in resolved_root.rglob("*") if not path.is_dir()),
            key=lambda path: path.relative_to(resolved_root).as_posix().casefold(),
        )
    )
    return _scan_candidates(
        candidates,
        roots=(resolved_root,),
        previous_hashes=previous_hashes,
        root_label=str(resolved_root),
    )


def _scan_candidates(
    candidates: tuple[tuple[Path, str, str], ...],
    *,
    roots: tuple[Path, ...],
    previous_hashes: Mapping[str, str] | None,
    root_label: str,
) -> InventoryResult:
    """Scan pre-labeled candidates as (path, display name, source namespace)."""

    previous = dict(previous_hashes or {})
    records: list[SourceRecord] = []
    new_ids: list[str] = []
    changed_ids: list[str] = []
    unchanged_ids: list[str] = []

    for path, display_name, source_namespace in candidates:
        source_id = _stable_source_id(source_namespace)
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
        root=root_label,
        records=tuple(records),
        new_source_ids=tuple(new_ids),
        changed_source_ids=tuple(changed_ids),
        unchanged_source_ids=tuple(unchanged_ids),
        deleted_source_ids=tuple(sorted(set(previous) - current_ids)),
        roots=tuple(str(root) for root in roots),
    )


def scan_paths(
    roots: tuple[str | Path, ...],
    *,
    previous_hashes: Mapping[str, str] | None = None,
) -> InventoryResult:
    if not roots:
        raise ValueError("at least one input root is required")
    resolved = tuple(Path(root).resolve() for root in roots)
    if len(set(resolved)) != len(resolved):
        raise ValueError("duplicate input roots are not allowed")
    for index, first in enumerate(resolved):
        if not first.exists():
            raise FileNotFoundError(first)
        for second in resolved[index + 1 :]:
            if first.is_relative_to(second) or second.is_relative_to(first):
                raise ValueError("overlapping input roots are not allowed")

    multiple = len(resolved) > 1
    candidates: list[tuple[Path, str, str]] = []
    for index, root in enumerate(resolved):
        if root.is_dir():
            paths = sorted(
                (path for path in root.rglob("*") if not path.is_dir()),
                key=lambda path: path.relative_to(root).as_posix().casefold(),
            )
            for path in paths:
                relative = path.relative_to(root).as_posix()
                display = f"{root.name}/{relative}" if multiple else relative
                candidates.append((path, display, f"root-{index}/{relative}"))
        elif root.is_file():
            candidates.append((root, root.name, f"root-{index}/{root.name}"))
        else:
            raise ValueError(f"unsupported input root: {root}")
    ordered = tuple(sorted(candidates, key=lambda item: (item[1].casefold(), item[2])))
    return _scan_candidates(
        ordered,
        roots=resolved,
        previous_hashes=previous_hashes,
        root_label=str(resolved[0]) if len(resolved) == 1 else "<multiple>",
    )
