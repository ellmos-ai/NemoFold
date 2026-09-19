"""Turn a gate acceptance bundle into evidence that can live in the repository.

A bundle run writes its artifacts wherever it was pointed, so its reports carry the
absolute path of that directory. Those bytes are honest but unusable as committed
evidence: they leak the operator's home directory and they change with every run,
which would make the hashes in the register churn without anything having changed.

This module copies the files a run receipt actually references into a stable tree,
replaces the run directory prefix with the ``<evidence-root>`` token, and rewrites
the receipt so its paths and SHA-256 values describe the exported bytes. Nothing
else is touched: run ids, statuses, claims and check results are carried over
unchanged, so what the register verifies is still the run that happened.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
from collections.abc import Iterator, Sequence
from importlib import import_module
from pathlib import Path
from typing import Any

from .acceptance_gates import artifact_manifest_sha256

EVIDENCE_ROOT_TOKEN = "<evidence-root>"
DEFAULT_EVIDENCE_DIR = Path("examples") / "acceptance-evidence"
_TEXT_SUFFIXES = frozenset({".json", ".md", ".txt", ".csv", ".yaml", ".yml"})


class EvidenceExportError(RuntimeError):
    """Raised when a bundle cannot be exported into committable evidence."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relativize(text: str, bundle_root: Path) -> str:
    """Replace every spelling of the run directory with the evidence-root token."""
    raw = str(bundle_root)
    # Derive every spelling from the string itself: on POSIX hosts ``as_posix()``
    # leaves a Windows path's backslashes untouched, so the forward-slash spelling
    # must be built explicitly or a run directory would survive relativisation.
    variants = sorted(
        {
            raw,
            raw.replace("\\", "\\\\"),
            raw.replace("\\", "/"),
            bundle_root.as_posix(),
        },
        key=len,
        reverse=True,
    )
    for variant in variants:
        text = re.sub(re.escape(variant), EVIDENCE_ROOT_TOKEN, text, flags=re.IGNORECASE)
    return text


def _receipt_paths(receipt: dict[str, Any]) -> Iterator[tuple[str, Any, str]]:
    """Yield (relative_path, container, key) for every file a receipt points at."""
    for direction in ("input", "output"):
        for artifact in receipt[f"{direction}_artifacts"]:
            yield artifact["path"], artifact, "path"
    for handoff in receipt["handoff_receipts"]:
        yield handoff["artifact_path"], handoff, "artifact_path"
    yield receipt["run_report"]["path"], receipt["run_report"], "path"
    for negative in (receipt["negative_path"], *receipt.get("additional_negative_paths", [])):
        yield negative["run_report"]["path"], negative["run_report"], "path"


def _find_bundle_register(bundle_root: Path, gate_id: str) -> Path:
    """Locate the register a bundle wrote, under either naming convention."""
    gate = gate_id.lower()
    candidates = (
        bundle_root / f"gate-register.{gate}.json",
        bundle_root / "evidence" / f"nf_fin_gates_{gate}.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for pattern in (f"**/gate-register.{gate}.json", f"**/nf_fin_gates_{gate}.json"):
        found = sorted(bundle_root.glob(pattern))
        if found:
            return found[0]
    raise EvidenceExportError(f"bundle_register_missing:{gate_id}")


def export_gate_evidence(
    gate_id: str,
    bundle_root: str | Path,
    repo_root: str | Path,
    *,
    evidence_dir: str | Path = DEFAULT_EVIDENCE_DIR,
) -> dict[str, Any]:
    """Export one bundle's run receipt into ``<repo_root>/<evidence_dir>/<gate>/``.

    Returns the rewritten receipt, whose paths are relative to ``repo_root`` and
    whose hashes describe the exported files.
    """
    source = Path(bundle_root).resolve()
    repo = Path(repo_root).resolve()
    if not source.is_dir():
        raise EvidenceExportError(f"bundle_root_not_a_directory:{source}")

    bundle_register = json.loads(
        _find_bundle_register(source, gate_id).read_text(encoding="utf-8")
    )
    gate = next(
        (item for item in bundle_register["gates"] if item["gate_id"] == gate_id),
        None,
    )
    if gate is None or not gate["evidence"]["run_receipts"]:
        raise EvidenceExportError(f"bundle_receipt_missing:{gate_id}")
    if len(gate["evidence"]["run_receipts"]) != 1:
        raise EvidenceExportError(f"bundle_receipt_not_unique:{gate_id}")

    target_dir = repo / Path(evidence_dir) / gate_id.lower()
    if target_dir.exists():
        shutil.rmtree(target_dir)

    receipt = json.loads(json.dumps(gate["evidence"]["run_receipts"][0]))
    prefix = (Path(evidence_dir) / gate_id.lower()).as_posix()
    for relative, container, key in _receipt_paths(receipt):
        origin = source / relative
        if not origin.is_file():
            raise EvidenceExportError(f"bundle_file_missing:{gate_id}:{relative}")
        destination = target_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if origin.suffix.casefold() in _TEXT_SUFFIXES:
            destination.write_text(
                _relativize(origin.read_text(encoding="utf-8"), source),
                encoding="utf-8",
                newline="",
            )
        else:
            destination.write_bytes(origin.read_bytes())
        container[key] = f"{prefix}/{Path(relative).as_posix()}"
        sha_key = "artifact_sha256" if key == "artifact_path" else "sha256"
        if sha_key in container:
            container[sha_key] = _sha256(destination)

    for direction in ("input", "output"):
        receipt[f"{direction}_sha256"] = artifact_manifest_sha256(
            receipt[f"{direction}_artifacts"]
        )
    return receipt


def collect_gate_test_nodes(repo_root: str | Path, gate_id: str) -> list[dict[str, str]]:
    """Collect the pytest nodes whose files are named for this gate.

    The register validates each node against the file's AST, so a node collected
    here that no longer exists fails the register rather than passing silently.
    """
    repo = Path(repo_root).resolve()
    tests_dir = repo / "tests"
    nodes: list[dict[str, str]] = []
    for path in sorted(tests_dir.rglob(f"test_{gate_id.lower()}_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(repo).as_posix()
        file_sha = _sha256(path)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
                "test_"
            ):
                nodes.append({"node": f"{relative}::{node.name}", "file_sha256": file_sha})
    if not nodes:
        raise EvidenceExportError(f"no_test_nodes_found:{gate_id}")
    return nodes


def build_done_evidence(
    gate_id: str,
    bundle_root: str | Path,
    repo_root: str | Path,
    *,
    evidence_dir: str | Path = DEFAULT_EVIDENCE_DIR,
) -> dict[str, Any]:
    """Return the ``evidence`` block a gate needs to claim ``done``."""
    return {
        "test_nodes": collect_gate_test_nodes(repo_root, gate_id),
        "run_receipts": [
            export_gate_evidence(gate_id, bundle_root, repo_root, evidence_dir=evidence_dir)
        ],
    }


def exported_gate_ids(
    repo_root: str | Path,
    *,
    evidence_dir: str | Path = DEFAULT_EVIDENCE_DIR,
) -> Sequence[str]:
    """List the gate ids that already have an exported evidence directory."""
    root = Path(repo_root).resolve() / Path(evidence_dir)
    if not root.is_dir():
        return ()
    return tuple(
        sorted(entry.name.upper() for entry in root.iterdir() if entry.is_dir())
    )


BUNDLED_GATE_IDS = tuple(f"G{number:02d}" for number in range(1, 17))


def rebuild_gate_evidence(
    repo_root: str | Path,
    work_dir: str | Path,
    *,
    gate_ids: Sequence[str] = BUNDLED_GATE_IDS,
    evidence_dir: str | Path = DEFAULT_EVIDENCE_DIR,
    register_path: str | Path | None = None,
) -> dict[str, Any]:
    """Re-run the gate bundles and rewrite the register they back.

    This is how the committed evidence is regenerated: a gate whose bundle no
    longer produces a verifiable receipt falls back to the status it had before,
    so a broken chain shows up as a gate losing ``done`` rather than as evidence
    quietly going stale.
    """
    from .acceptance_gates import (  # imported late: the register imports nothing from here
        GateRegisterError,
        load_gate_register_template,
        summarize_gate_register,
        verify_gate_evidence,
    )

    repo = Path(repo_root).resolve()
    work = Path(work_dir).resolve()
    register = load_gate_register_template(register_path)
    promoted: list[str] = []
    refused: dict[str, str] = {}

    for gate_id in gate_ids:
        module = import_module(f".{gate_id.lower()}_acceptance", package=__package__)
        runner = getattr(module, f"run_{gate_id.lower()}_acceptance_bundle")
        bundle_root = work / gate_id.lower()
        if bundle_root.exists():
            shutil.rmtree(bundle_root)
        try:
            runner(bundle_root)
            evidence = build_done_evidence(
                gate_id, bundle_root, repo, evidence_dir=evidence_dir
            )
        except (EvidenceExportError, OSError, RuntimeError, ValueError) as exc:
            refused[gate_id] = f"{type(exc).__name__}: {exc}"
            continue
        candidate = json.loads(json.dumps(register))
        target = next(item for item in candidate["gates"] if item["gate_id"] == gate_id)
        target["status"] = "done"
        target["evidence"] = evidence
        try:
            verify_gate_evidence(candidate, repo)
        except GateRegisterError as exc:
            refused[gate_id] = str(exc)
            continue
        register = candidate
        promoted.append(gate_id)

    destination = Path(register_path) if register_path else _packaged_register_path()
    payload = json.dumps(register, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_bytes(payload.encode("utf-8"))
    os.replace(temporary, destination)

    return {
        "register_path": str(destination),
        "promoted": promoted,
        "refused": refused,
        "summary": summarize_gate_register(register, evidence_root=repo),
    }


def _packaged_register_path() -> Path:
    from importlib.resources import files

    return Path(str(files("nemofold").joinpath("data", "nf_fin_gates.json")))
