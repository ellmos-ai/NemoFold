from __future__ import annotations

import json

from nemofold.contracts import (
    ActionMode,
    JobEnvelope,
    PrivacyMode,
    SourceRecord,
    to_primitive,
)


def test_external_payload_uses_source_ids_without_local_paths(tmp_path) -> None:
    source = SourceRecord(
        source_id="src_01",
        path=str(tmp_path / "private" / "contract.pdf"),
        display_name="insurance/contract.pdf",
        sha256="a" * 64,
        mime_type="application/pdf",
    )
    job = JobEnvelope(
        workflow="evidence_analyst",
        input_roots=(str(tmp_path / "private"),),
        output_dir=str(tmp_path / "output"),
        questions=("Which policy is current?",),
        privacy_mode=PrivacyMode.ALLOW_ONCE,
        action_mode=ActionMode.DRY_RUN,
        model_id="nvidia/nemotron",
        model_budget_usd=1.5,
        sources=(source,),
    )

    payload = job.to_external_payload()
    encoded = json.dumps(payload, sort_keys=True)

    assert payload["sources"] == [
        {
            "display_name": "insurance/contract.pdf",
            "mime_type": "application/pdf",
            "sha256": "a" * 64,
            "source_id": "src_01",
        }
    ]
    assert str(tmp_path) not in encoded
    assert "input_roots" not in payload
    assert "output_dir" not in payload


def test_contract_serialization_is_json_safe_and_deterministic(tmp_path) -> None:
    job = JobEnvelope(
        workflow="folder_digest",
        input_roots=(str(tmp_path),),
        output_dir=str(tmp_path / "out"),
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        action_mode=ActionMode.DRY_RUN,
    )

    first = json.dumps(to_primitive(job), sort_keys=True)
    second = json.dumps(to_primitive(job), sort_keys=True)

    assert first == second
    assert '"privacy_mode": "local_only"' in first
