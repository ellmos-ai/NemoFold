from __future__ import annotations

import json
from pathlib import Path

from nemofold.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_acceptance_gates_cli_refuses_done_claims_without_an_evidence_root(capsys) -> None:
    assert main(["acceptance-gates"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert any("done_gate_requires_evidence_root" in error for error in payload["errors"])


def test_acceptance_gates_cli_refuses_an_evidence_root_without_the_files(
    tmp_path, capsys
) -> None:
    assert main(["acceptance-gates", "--evidence-root", str(tmp_path)]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert any("evidence_file_missing" in error for error in payload["errors"])


def test_acceptance_gates_cli_reports_the_register_against_the_committed_evidence(
    capsys,
) -> None:
    assert main(["acceptance-gates", "--evidence-root", str(REPO_ROOT)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["catalog_verification"] is None
    assert len(payload["register"]["gates"]) == 18
    assert payload["summary"]["counts"]["done"] == 16
    assert payload["summary"]["counts"]["planned"] == 0
    assert payload["summary"]["open_gates"] == ["G17", "G18"]
    assert payload["gate_evidence_verification"]["checked_file_count"] > 0
