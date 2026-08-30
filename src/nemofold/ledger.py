from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from .contracts import ArtifactRecord, Coverage, GateDecision, RunReport, RunStatus, to_primitive

RUN_ID_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


def validate_run_id(run_id: str) -> str:
    if not run_id or any(character not in RUN_ID_CHARACTERS for character in run_id):
        raise ValueError("run_id must contain only letters, numbers, underscores, or hyphens")
    return run_id


class LedgerCollisionError(RuntimeError):
    pass


class InvalidTransitionError(RuntimeError):
    pass


ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PLANNED: frozenset({RunStatus.RUNNING, RunStatus.BLOCKED, RunStatus.FAILED}),
    RunStatus.RUNNING: frozenset({RunStatus.EXECUTED, RunStatus.BLOCKED, RunStatus.FAILED}),
    RunStatus.BLOCKED: frozenset({RunStatus.RUNNING, RunStatus.FAILED}),
    RunStatus.FAILED: frozenset({RunStatus.RUNNING, RunStatus.BLOCKED}),
    RunStatus.EXECUTED: frozenset(),
}


class RunLedger:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        return self.root / f"{validate_run_id(run_id)}.json"

    @staticmethod
    def _encode(report: RunReport) -> bytes:
        return (json.dumps(to_primitive(report), indent=2, sort_keys=True) + "\n").encode("utf-8")

    def _atomic_write(self, path: Path, data: bytes) -> None:
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

    def save(self, report: RunReport) -> Path:
        path = self._path(report.run_id)
        data = self._encode(report)
        if path.exists():
            if path.read_bytes() == data:
                return path
            raise LedgerCollisionError(
                f"run_id already exists with different content: {report.run_id}"
            )
        self._atomic_write(path, data)
        return path

    def _replace(self, report: RunReport) -> None:
        self._atomic_write(self._path(report.run_id), self._encode(report))

    def load(self, run_id: str) -> RunReport:
        data: dict[str, Any] = json.loads(self._path(run_id).read_text(encoding="utf-8"))
        gate_data = data.get("gate_decision")
        coverage_data = data.get("coverage")
        return RunReport(
            run_id=data["run_id"],
            idempotency_key=data["idempotency_key"],
            workflow=data["workflow"],
            status=RunStatus(data["status"]),
            actions=tuple(data.get("actions", ())),
            errors=tuple(data.get("errors", ())),
            gate_decision=(
                GateDecision(
                    allowed=gate_data["allowed"],
                    reasons=tuple(gate_data.get("reasons", ())),
                    allowed_fields=tuple(gate_data.get("allowed_fields", ())),
                    recipient=gate_data.get("recipient"),
                    max_cost_usd=gate_data.get("max_cost_usd", 0.0),
                )
                if gate_data
                else None
            ),
            coverage=(
                Coverage(
                    total_sources=coverage_data["total_sources"],
                    read_sources=coverage_data["read_sources"],
                    cited_sources=coverage_data["cited_sources"],
                    unread_source_ids=tuple(coverage_data.get("unread_source_ids", ())),
                    uncited_read_source_ids=tuple(
                        coverage_data.get("uncited_read_source_ids", ())
                    ),
                )
                if coverage_data
                else None
            ),
            artifacts=tuple(ArtifactRecord(**item) for item in data.get("artifacts", ())),
            metadata=data.get("metadata", {}),
        )

    def transition(self, run_id: str, new_status: RunStatus) -> RunReport:
        report = self.load(run_id)
        updated = replace(report, status=new_status)
        return self.update(updated)

    def update(self, report: RunReport) -> RunReport:
        current = self.load(report.run_id)
        if (
            report.idempotency_key != current.idempotency_key
            or report.workflow != current.workflow
        ):
            raise LedgerCollisionError("run identity cannot change during an update")
        if (
            report.status is not current.status
            and report.status not in ALLOWED_TRANSITIONS[current.status]
        ):
            raise InvalidTransitionError(
                f"invalid transition: {current.status.value} -> {report.status.value}"
            )
        self._replace(report)
        return report
