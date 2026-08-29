from __future__ import annotations

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
        questions=("What is confirmed?",),
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
        question="What is confirmed?",
        hits=(
            SearchHit(
                chunk_id="src_a:000000",
                source_id="src_a",
                text="The synthetic fact is confirmed.",
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
    )
    validation = validate_job_package(package.path)
    encoded = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(package.path.glob("*.json"))
    )

    assert validation.valid is True
    assert validation.errors == ()
    assert str(tmp_path) not in encoded
    assert "real-secret-name" not in encoded
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
