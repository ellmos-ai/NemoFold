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
