from __future__ import annotations

import hashlib
import json

import pytest

from nemofold.contracts import ActionMode, JobEnvelope, PrivacyMode, SourceRecord
from nemofold.document_index import SearchHit
from nemofold.evidence_analyst import ContextReceipt
from nemofold.nemoclaw_package import export_job_package, validate_job_package
from nemofold.policy import PolicyConfig, PolicyGate


def make_job(tmp_path) -> JobEnvelope:
    approved = tmp_path / "private"
    approved.mkdir()
    return JobEnvelope(
        workflow="evidence_analyst",
        input_roots=(str(approved),),
        output_dir=str(approved / "out"),
        questions=("What did Lukas Example send to analyst@example.org?",),
        privacy_mode=PrivacyMode.ALLOW_ONCE,
        action_mode=ActionMode.DRY_RUN,
        model_id="nvidia/nemotron-3-super-120b-a12b",
        model_budget_usd=1.0,
        sources=(
            SourceRecord(
                source_id="src_a",
                path=str(approved / "real-secret-name.txt"),
                display_name="case/current.txt",
                sha256="a" * 64,
                mime_type="text/plain",
            ),
        ),
    )


def receipt() -> ContextReceipt:
    return ContextReceipt(
        question="What did Lukas Example send to analyst@example.org?",
        hits=(
            SearchHit(
                chunk_id="src_a:000000",
                source_id="src_a",
                text=(
                    "The synthetic fact is confirmed by analyst@example.org. "
                    "Private file C:\\Users\\lukas\\case.txt belongs to Lukas Example."
                ),
                rank=-1.0,
            ),
        ),
    )


def test_job_package_is_path_free_hashed_and_valid(tmp_path) -> None:
    job = make_job(tmp_path)
    decision = PolicyGate(
        PolicyConfig(
            allowed_roots=job.input_roots,
            external_models_allowed=True,
            max_external_cost_usd=1.0,
        )
    ).evaluate(job)

    package = export_job_package(
        job,
        (receipt(),),
        decision,
        tmp_path / "package",
        run_id="run_external_001",
        sensitive_terms=("Lukas Example",),
    )
    validation = validate_job_package(package.path)
    encoded = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(package.path.glob("*.json"))
    )

    assert validation.valid is True
    assert validation.errors == ()
    assert str(tmp_path) not in encoded
    assert "real-secret-name" not in encoded
    assert "analyst@example.org" not in encoded
    assert "C:\\Users\\lukas" not in encoded
    assert "Lukas Example" not in encoded
    assert "<EMAIL_001>" in encoded
    privacy = json.loads((package.path / "privacy-receipt.json").read_text(encoding="utf-8"))
    assert privacy["replacement_counts"] == {"EMAIL": 1, "PATH": 1, "TERM": 1}
    assert json.loads((package.path / "job.json").read_text(encoding="utf-8"))["model"][
        "id"
    ] == "nvidia/nemotron-3-super-120b-a12b"


def test_package_tampering_is_detected(tmp_path) -> None:
    job = make_job(tmp_path)
    decision = PolicyGate(
        PolicyConfig(
            allowed_roots=job.input_roots,
            external_models_allowed=True,
            max_external_cost_usd=1.0,
        )
    ).evaluate(job)
    package = export_job_package(
        job,
        (receipt(),),
        decision,
        tmp_path / "package",
        run_id="run_external_002",
    )
    (package.path / "context-receipts.json").write_text("[]\n", encoding="utf-8")

    validation = validate_job_package(package.path)

    assert validation.valid is False
    assert "hash_mismatch:context-receipts.json" in validation.errors


def test_blocked_gate_cannot_export_external_package(tmp_path) -> None:
    job = make_job(tmp_path)
    blocked = PolicyGate(PolicyConfig(allowed_roots=job.input_roots)).evaluate(job)

    with pytest.raises(PermissionError):
        export_job_package(
            job,
            (receipt(),),
            blocked,
            tmp_path / "package",
            run_id="run_blocked",
        )


def test_validator_rejects_rehashed_raw_identifier_and_source_name(tmp_path) -> None:
    job = make_job(tmp_path)
    decision = PolicyGate(
        PolicyConfig(
            allowed_roots=job.input_roots,
            external_models_allowed=True,
            max_external_cost_usd=1.0,
        )
    ).evaluate(job)
    package = export_job_package(
        job,
        (receipt(),),
        decision,
        tmp_path / "package",
        run_id="run_external_003",
        sensitive_terms=("Lukas Example",),
    )
    job_path = package.path / "job.json"
    job_payload = json.loads(job_path.read_text(encoding="utf-8"))
    job_payload["questions"] = ["Contact leaked@example.org"]
    job_payload["sources"][0]["display_name"] = "private-name.txt"
    job_bytes = (json.dumps(job_payload, indent=2, sort_keys=True) + "\n").encode()
    job_path.write_bytes(job_bytes)
    manifest_path = package.path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["job.json"] = hashlib.sha256(job_bytes).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    validation = validate_job_package(package.path)

    assert validation.valid is False
    assert "sensitive_data_detected:EMAIL" in validation.errors
    assert "source_metadata_forbidden" in validation.errors


def test_validator_rejects_undeclared_package_entries(tmp_path) -> None:
    job = make_job(tmp_path)
    decision = PolicyGate(
        PolicyConfig(
            allowed_roots=job.input_roots,
            external_models_allowed=True,
            max_external_cost_usd=1.0,
        )
    ).evaluate(job)
    package = export_job_package(
        job,
        (receipt(),),
        decision,
        tmp_path / "package",
        run_id="run_external_004",
        sensitive_terms=("Lukas Example",),
    )
    (package.path / "extra.txt").write_text("undeclared", encoding="utf-8")

    validation = validate_job_package(package.path)

    assert validation.valid is False
    assert "undeclared_entry:extra.txt" in validation.errors
