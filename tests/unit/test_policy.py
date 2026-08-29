from __future__ import annotations

from dataclasses import replace

from nemofold.contracts import ActionMode, JobEnvelope, PrivacyMode
from nemofold.policy import PolicyConfig, PolicyGate


def make_job(tmp_path, **changes) -> JobEnvelope:
    root = tmp_path / "approved"
    root.mkdir(exist_ok=True)
    base = JobEnvelope(
        workflow="folder_digest",
        input_roots=(str(root),),
        output_dir=str(root / "out"),
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        action_mode=ActionMode.DRY_RUN,
    )
    return replace(base, **changes)


def test_local_job_inside_allowlist_is_allowed(tmp_path) -> None:
    job = make_job(tmp_path)
    gate = PolicyGate(PolicyConfig(allowed_roots=job.input_roots))

    decision = gate.evaluate(job)

    assert decision.allowed is True
    assert decision.reasons == ()


def test_path_outside_allowlist_is_blocked(tmp_path) -> None:
    job = make_job(tmp_path, output_dir=str(tmp_path / "not-approved"))
    gate = PolicyGate(PolicyConfig(allowed_roots=(job.input_roots[0],)))

    decision = gate.evaluate(job)

    assert decision.allowed is False
    assert "output_path_not_allowed" in decision.reasons


def test_external_model_requires_allow_once_and_positive_bounded_budget(tmp_path) -> None:
    local = make_job(tmp_path, model_id="nvidia/nemotron")
    config = PolicyConfig(
        allowed_roots=local.input_roots,
        external_models_allowed=True,
        max_external_cost_usd=2.0,
    )
    gate = PolicyGate(config)

    privacy_block = gate.evaluate(local)
    zero_block = gate.evaluate(
        replace(local, privacy_mode=PrivacyMode.ALLOW_ONCE, model_budget_usd=0)
    )
    cost_block = gate.evaluate(
        replace(local, privacy_mode=PrivacyMode.ALLOW_ONCE, model_budget_usd=2.01)
    )
    allowed = gate.evaluate(
        replace(local, privacy_mode=PrivacyMode.ALLOW_ONCE, model_budget_usd=2.0)
    )

    assert "external_privacy_not_approved" in privacy_block.reasons
    assert "external_budget_missing" in zero_block.reasons
    assert "external_budget_exceeds_limit" in cost_block.reasons
    assert allowed.allowed is True
    assert "path" not in allowed.allowed_fields
