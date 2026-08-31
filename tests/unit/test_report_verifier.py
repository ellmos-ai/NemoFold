from __future__ import annotations

import hashlib
import json

import pytest

from nemofold.report_verifier import verify_run_report


def write_report(tmp_path, **overrides):
    artifact = tmp_path / "report.md"
    artifact.write_text("verified artifact\n", encoding="utf-8")
    payload = {
        "run_id": "run_001",
        "idempotency_key": "job_" + "a" * 64,
        "workflow": "evidence_analyst",
        "status": "executed",
        "actions": ["claims_validated"],
        "errors": [],
        "coverage": {
            "total_sources": 2,
            "read_sources": 2,
            "cited_sources": 1,
            "unread_source_ids": [],
            "uncited_read_source_ids": ["src_b"],
        },
        "artifacts": [
            {
                "format": "markdown",
                "path": str(artifact),
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "status": "written",
            }
        ],
        "metadata": {"cloud_proof": False},
    }
    payload.update(overrides)
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    path = ledger / "run_001.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, artifact


def test_report_verifier_checks_contract_coverage_and_artifact_hashes(tmp_path) -> None:
    path, _ = write_report(tmp_path)

    result = verify_run_report(path)

    assert result.valid is True
    assert result.errors == ()
    assert result.checked_artifacts == 1


def test_report_verifier_detects_artifact_tampering(tmp_path) -> None:
    path, artifact = write_report(tmp_path)
    artifact.write_text("tampered\n", encoding="utf-8")

    result = verify_run_report(path)

    assert result.valid is False
    assert "artifact_hash_mismatch:report.md" in result.errors


def test_report_verifier_rejects_impossible_coverage_and_unsupported_cloud_claim(tmp_path) -> None:
    path, _ = write_report(
        tmp_path,
        coverage={
            "total_sources": 1,
            "read_sources": 2,
            "cited_sources": 2,
            "unread_source_ids": [],
            "uncited_read_source_ids": [],
        },
        metadata={"cloud_proof": True},
    )

    result = verify_run_report(path)

    assert result.valid is False
    assert "coverage_counts_invalid" in result.errors
    assert "cloud_proof_requires_verified_result_package" in result.errors


def test_report_verifier_rejects_self_declared_live_runtime_metadata(tmp_path) -> None:
    path, _ = write_report(
        tmp_path,
        metadata={
            "cloud_proof": True,
            "live_runtime_evidence": {
                "nemoclaw_version": "self-declared",
                "model_id": "self-declared",
                "verbatim_log_sha256": "a" * 64,
            },
        },
    )

    result = verify_run_report(path)

    assert result.valid is False
    assert "cloud_proof_requires_verified_result_package" in result.errors


@pytest.mark.parametrize("false_proof", [True, 1, 0, "true", "false", None])
def test_report_verifier_rejects_every_explicit_non_false_cloud_claim(
    tmp_path, false_proof: object
) -> None:
    path, _ = write_report(tmp_path, metadata={"cloud_proof": false_proof})

    result = verify_run_report(path)

    assert result.valid is False
    assert "cloud_proof_requires_verified_result_package" in result.errors


def test_report_verifier_rejects_artifacts_outside_the_run_root(tmp_path) -> None:
    path, _ = write_report(tmp_path)
    outside = tmp_path.parent / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["artifacts"][0]["path"] = str(outside)
    payload["artifacts"][0]["sha256"] = hashlib.sha256(outside.read_bytes()).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = verify_run_report(path)

    assert result.valid is False
    assert "artifact_outside_run_root:outside.md" in result.errors


def test_report_verifier_refuses_artifacts_beyond_the_allowed_roots(tmp_path) -> None:
    path, _ = write_report(tmp_path)

    unrestricted = verify_run_report(path)
    covering = verify_run_report(path, allowed_roots=[tmp_path])
    bounded = verify_run_report(path, allowed_roots=[tmp_path / "ledger"])

    assert unrestricted.valid is True
    assert covering.valid is True
    assert bounded.valid is False
    assert "artifact_outside_allow_roots:report.md" in bounded.errors
    assert bounded.checked_artifacts == 0
