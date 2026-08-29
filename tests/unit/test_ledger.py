from __future__ import annotations

import pytest

from nemofold.contracts import RunReport, RunStatus
from nemofold.ledger import InvalidTransitionError, RunLedger


def test_run_ledger_persists_and_reloads_report(tmp_path) -> None:
    ledger = RunLedger(tmp_path)
    report = RunReport(
        run_id="run_001",
        idempotency_key="job_001",
        workflow="folder_digest",
        status=RunStatus.PLANNED,
    )

    first_path = ledger.save(report)
    second_path = ledger.save(report)
    loaded = ledger.load("run_001")

    assert first_path == second_path
    assert loaded == report


def test_terminal_run_cannot_return_to_running(tmp_path) -> None:
    ledger = RunLedger(tmp_path)
    ledger.save(
        RunReport(
            run_id="run_done",
            idempotency_key="job_done",
            workflow="folder_digest",
            status=RunStatus.EXECUTED,
        )
    )

    with pytest.raises(InvalidTransitionError):
        ledger.transition("run_done", RunStatus.RUNNING)


def test_failed_run_can_resume_without_changing_identity(tmp_path) -> None:
    ledger = RunLedger(tmp_path)
    ledger.save(
        RunReport(
            run_id="run_retry",
            idempotency_key="stable-key",
            workflow="evidence_analyst",
            status=RunStatus.FAILED,
            errors=("temporary_failure",),
        )
    )

    resumed = ledger.transition("run_retry", RunStatus.RUNNING)

    assert resumed.run_id == "run_retry"
    assert resumed.idempotency_key == "stable-key"
    assert resumed.status is RunStatus.RUNNING
