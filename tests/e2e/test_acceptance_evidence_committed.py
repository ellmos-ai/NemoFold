"""The packaged gate register must verify against the evidence committed in this repo.

A gate that claims ``done`` is only worth the file it can still open. These tests
open them: they resolve every evidence pointer of the packaged register against a
fresh checkout, re-hash the referenced bytes and reject host-specific paths that
would make the evidence unusable anywhere but the machine that produced it.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from nemofold.acceptance_gates import (
    GateRegisterError,
    load_gate_register,
    summarize_gate_register,
    verify_gate_evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPO_ROOT / "examples" / "acceptance-evidence"
HOST_PATH = re.compile(r"[A-Za-z]:[\\/]{1,2}(?:Users|_Local_DEV|home|tmp)", re.IGNORECASE)


def test_packaged_register_reaches_done_against_the_committed_evidence_root() -> None:
    register = load_gate_register(evidence_root=REPO_ROOT)
    summary = summarize_gate_register(register, evidence_root=REPO_ROOT)

    assert summary["counts"]["done"] >= 1, "no gate is backed by committed evidence"

    verification = verify_gate_evidence(register, REPO_ROOT)
    done_ids = [gate["gate_id"] for gate in register["gates"] if gate["status"] == "done"]
    assert verification["verified_done_gates"] == done_ids
    assert verification["checked_file_count"] >= len(done_ids)


def test_done_gates_carry_test_nodes_and_receipts() -> None:
    register = load_gate_register(evidence_root=REPO_ROOT)
    for gate in register["gates"]:
        if gate["status"] != "done":
            continue
        evidence = gate["evidence"]
        assert evidence["test_nodes"], f"{gate['gate_id']} claims done without a test node"
        assert evidence["run_receipts"], f"{gate['gate_id']} claims done without a receipt"
        for receipt in evidence["run_receipts"]:
            assert receipt["run_report"]["status"] == "executed"
            assert receipt["negative_path"]["blocked_as_expected"] is True


def test_committed_evidence_is_free_of_host_specific_paths() -> None:
    offenders: list[str] = []
    for path in sorted(EVIDENCE_ROOT.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
        if HOST_PATH.search(text):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert not offenders, f"committed evidence leaks host paths: {offenders[:5]}"


def test_missing_evidence_root_is_refused_for_done_gates() -> None:
    with pytest.raises(GateRegisterError, match="done_gate_requires_evidence_root"):
        load_gate_register()


def test_tampering_with_one_evidence_byte_fails_the_register(tmp_path: Path) -> None:
    """A copied evidence root with one flipped byte must not verify."""
    register = load_gate_register(evidence_root=REPO_ROOT)
    done_gate = next(gate for gate in register["gates"] if gate["status"] == "done")
    receipt = done_gate["evidence"]["run_receipts"][0]
    target = receipt["output_artifacts"][0]["path"]

    gate_dir = Path("examples") / "acceptance-evidence" / done_gate["gate_id"].lower()
    sources = [path for path in (REPO_ROOT / gate_dir).rglob("*") if path.is_file()]
    sources += [
        REPO_ROOT / node["node"].split("::", 1)[0] for node in done_gate["evidence"]["test_nodes"]
    ]
    for source in sources:
        destination = tmp_path / source.relative_to(REPO_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    (tmp_path / target).write_bytes((tmp_path / target).read_bytes() + b"tampered\n")

    single = json.loads(json.dumps(register))
    single["gates"] = [
        gate if gate["gate_id"] != done_gate["gate_id"] else done_gate
        for gate in single["gates"]
    ]
    for gate in single["gates"]:
        if gate["gate_id"] != done_gate["gate_id"]:
            gate["status"] = "planned" if gate["status"] == "done" else gate["status"]
            gate["evidence"] = {"test_nodes": gate["evidence"]["test_nodes"], "run_receipts": []}

    with pytest.raises(GateRegisterError, match="evidence_sha256_mismatch"):
        verify_gate_evidence(single, tmp_path)


def test_git_hands_evidence_bytes_back_unchanged() -> None:
    """Evidence is bound by its bytes, so git must not normalise its line endings.

    A CRLF mail draft under G12 once verified locally and failed in a fresh clone,
    because the checkout rewrote it to LF and the SHA-256 no longer matched.
    """
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")

    candidates = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted(EVIDENCE_ROOT.rglob("*"))
        if path.is_file() and b"\r\n" in path.read_bytes()
    ]
    if not candidates:
        candidates = [
            next(EVIDENCE_ROOT.rglob("*.json")).relative_to(REPO_ROOT).as_posix()
        ]

    result = subprocess.run(
        ["git", "check-attr", "text", "--", *candidates],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    unprotected = [line for line in result.stdout.splitlines() if not line.endswith(": unset")]
    assert not unprotected, f"git may rewrite these evidence files: {unprotected[:3]}"
