"""Console hardening found in the 2026-10 review: hostile headers and bodies.

Raw sockets on purpose: urllib normalises the Host header and refuses malformed
ones, and these tests are exactly about requests a browser under a rebinding
attack, or a careless client, would really send.
"""

from __future__ import annotations

import json
import socket
import threading
from contextlib import contextmanager

import pytest

from nemofold.application import ExecutionConfig, undo_run
from nemofold.webapp import WebAppConfig, _folder_listing, build_server


@contextmanager
def _server(tmp_path, **options):
    server = build_server(
        WebAppConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
            **options,
        ),
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _exchange(server, request: bytes) -> tuple[int, dict]:
    with socket.create_connection(server.server_address[:2], timeout=10) as connection:
        connection.sendall(request)
        received = b""
        while chunk := connection.recv(65536):
            received += chunk
    assert received, "the server closed the connection without answering"
    head, _, body = received.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    return status, json.loads(body) if body.strip() else {}


def _get(server, path: str, host: str) -> tuple[int, dict]:
    return _exchange(
        server, f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode()
    )


def _post(server, path: str, body: bytes, host: str = "127.0.0.1", extra: str = ""):
    head = (
        f"POST {path} HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n{extra}\r\n"
    )
    return _exchange(server, head.encode() + body)


def test_a_rebinding_host_cannot_read_the_console(tmp_path) -> None:
    with _server(tmp_path) as server:
        port = server.server_address[1]
        trusted, _ = _get(server, "/api/status", f"127.0.0.1:{port}")
        for path in ("/api/status", "/api/drafts", "/api/voyages", "/"):
            status, payload = _get(server, path, f"rebind.attacker.example:{port}")
            assert status == 403, path
            assert payload["error"] == "host_rejected"

    assert trusted == 200


def test_malformed_host_and_origin_are_refused_not_crashed(tmp_path) -> None:
    with _server(tmp_path) as server:
        bad_host, _ = _post(server, "/api/folders", b"{}", host="[")
        bad_origin, payload = _post(server, "/api/folders", b"{}", extra="Origin: http://[\r\n")

    assert bad_host == 403
    assert bad_origin == 403
    assert payload["error"] == "origin_rejected"


def test_a_nesting_bomb_is_a_bad_request(tmp_path) -> None:
    body = b"[" * 100000 + b"]" * 100000
    with _server(tmp_path) as server:
        for path in ("/api/folders", "/api/wizard"):
            status, _ = _post(server, path, body)
            assert status == 400, path


def test_the_public_demo_refuses_unhashable_fields(tmp_path) -> None:
    source = tmp_path / "demo"
    source.mkdir()
    (source / "note.txt").write_text("Ein Satz.", encoding="utf-8")
    job = {
        "schema": "nemofold.job.v1",
        "workflow": ["folder_digest"],
        "input_roots": ["demo://synthetic-home"],
        "output_dir": "demo://ephemeral",
    }
    with _server(
        tmp_path, public_demo=True, demo_source_root=source, max_parallel_jobs=1
    ) as server:
        listed, listed_payload = _post(server, "/api/preview", json.dumps({"job": job}).encode())
        job["workflow"] = "folder_digest"
        job["model_id"] = {"x": 1}
        mapped, mapped_payload = _post(server, "/api/preview", json.dumps({"job": job}).encode())

    assert listed == 400
    assert "workflow" in listed_payload["detail"]
    assert mapped == 400
    assert "model_id" in mapped_payload["detail"]


def test_a_symlink_does_not_make_a_complete_listing_look_cut(tmp_path, monkeypatch) -> None:
    # A cap of one folder makes the edge case cheap: one real folder fills it.
    monkeypatch.setattr("nemofold.webapp.MAX_FOLDER_CHOICES", 1)
    root = tmp_path / "root"
    root.mkdir()
    (root / "akte").mkdir()
    try:
        (root / "link").symlink_to(root / "akte", target_is_directory=True)
    except OSError:
        pytest.skip("creating a symlink needs a privilege this host does not grant")
    config = WebAppConfig(base_dir=root, execution=ExecutionConfig(allowed_roots=(str(root),)))

    listing = _folder_listing(config, requested_path=str(root))

    assert listing["skipped_count"] == 1
    assert listing["truncated"] is False


def test_a_failed_undo_can_be_retried(tmp_path) -> None:
    from nemofold.action_journal import ActionJournal
    from nemofold.contracts import GateDecision, RunReport, RunStatus
    from nemofold.ledger import RunLedger
    from nemofold.storage_policy import PolicyRule, preview_storage

    inbox, archive, out = tmp_path / "inbox", tmp_path / "archive", tmp_path / "out"
    for folder in (inbox, archive, out):
        folder.mkdir()
    (inbox / "a.txt").write_text("alpha", encoding="utf-8")
    rule = PolicyRule(scope=inbox, allowed_extensions=(".txt",), original_policy="move")
    plans = (preview_storage(inbox / "a.txt", archive, rule),)
    journal = ActionJournal(out / "actions" / "r1.json", run_id="r1")
    journal.plan(plans)
    journal.execute(plans)
    RunLedger(out / "ledger").save(
        RunReport(
            run_id="r1",
            idempotency_key="k",
            workflow="storage_policy",
            status=RunStatus.EXECUTED,
            gate_decision=GateDecision(allowed=True),
        )
    )
    config = ExecutionConfig(allowed_roots=(str(tmp_path),), apply_actions_allowed=True)

    (inbox / "a.txt").write_text("in the way", encoding="utf-8")
    first = undo_run(out, config, run_id="r1")
    (inbox / "a.txt").unlink()
    second = undo_run(out, config, run_id="r1")

    assert first.report.status is RunStatus.FAILED
    assert second.report.status is RunStatus.EXECUTED
    assert second.report.errors == ()
    assert (inbox / "a.txt").read_text(encoding="utf-8") == "alpha"
