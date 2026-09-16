from __future__ import annotations

import json

from nemofold.cli import main


def test_acceptance_gates_cli_reports_open_register(capsys) -> None:
    assert main(["acceptance-gates"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["summary"]["complete"] is False
    assert payload["summary"]["counts"]["done"] == 0
    assert payload["catalog_verification"] is None
    assert len(payload["register"]["gates"]) == 18


def test_acceptance_gates_cli_verifies_empty_done_set_against_evidence_root(
    tmp_path, capsys
) -> None:
    assert main(["acceptance-gates", "--evidence-root", str(tmp_path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["gate_evidence_verification"] == {
        "checked_file_count": 0,
        "checked_files": [],
        "evidence_root": str(tmp_path.resolve()),
        "verified_evidence_gates": [],
        "verified_done_gates": [],
    }
