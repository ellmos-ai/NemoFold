from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from nemofold.application import ExecutionConfig
from nemofold.contracts import ActionMode, JobEnvelope, PrivacyMode, RunStatus
from nemofold.provider_analysis import analyze_with_provider
from nemofold.providers import ProviderConfig, ProviderRequest, ProviderResponse
from nemofold.report_verifier import verify_run_report


@dataclass
class EvidenceAdapter:
    config: ProviderConfig
    bad_quote: bool = False
    provider_id: str | None = None
    uncertainty: float | bool = 0.1
    request: ProviderRequest | None = None

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.request = request
        context = json.loads(request.user_prompt)
        chunk = context["receipts"][0]["chunks"][0]
        quote = "Invented evidence." if self.bad_quote else chunk["text"]
        return ProviderResponse(
            text=json.dumps(
                {
                    "answers": [
                        {
                            "question_id": "q_001",
                            "statement": "The supplied document supports the answer.",
                            "evidence": [{"source_id": chunk["source_id"], "quote": quote}],
                            "uncertainty": self.uncertainty,
                            "conflict_status": "none",
                        }
                    ],
                    "unanswered_question_ids": [],
                }
            ),
            provider_id=self.provider_id or self.config.provider_id,
            model=self.config.model,
            usage={"input_tokens": 10, "output_tokens": 5},
            request_id="provider-request-1",
        )


def make_job(tmp_path, *, privacy_mode=PrivacyMode.LOCAL_ONLY, budget=0.0):
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "case.txt").write_text(
        "Lukas Example confirmed coverage on 1 April. Contact analyst@example.org.",
        encoding="utf-8",
    )
    return JobEnvelope(
        workflow="evidence_analyst",
        input_roots=(str(documents),),
        output_dir=str(tmp_path / "output"),
        questions=("What did Lukas Example confirm for analyst@example.org?",),
        privacy_mode=privacy_mode,
        action_mode=ActionMode.DRY_RUN,
        model_budget_usd=budget,
        parameters={
            "formats": ["md"],
            "max_chunks": 4,
            "pseudonymize_terms": ["Lukas Example"],
        },
    )


def test_local_provider_analysis_anonymizes_then_validates_every_quote(tmp_path) -> None:
    job = make_job(tmp_path)
    provider = ProviderConfig(provider_id="ollama", model="qwen3")
    adapter = EvidenceAdapter(provider)

    result = analyze_with_provider(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        provider,
        run_id="ollama_analysis",
        adapter=adapter,
    )

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["transfer_performed"] is False
    assert result.report.metadata["provider_execution_proof"] is True
    assert result.report.metadata["competition_proof"] is False
    assert result.report.metadata["cloud_proof"] is False
    assert result.report.coverage.cited_sources == 1
    assert adapter.request is not None
    assert "Lukas Example" not in adapter.request.user_prompt
    assert "analyst@example.org" not in adapter.request.user_prompt
    assert str(tmp_path) not in adapter.request.user_prompt
    assert "<TERM_001>" in adapter.request.user_prompt
    assert "<EMAIL_001>" in adapter.request.user_prompt
    answers_schema = adapter.request.response_schema["properties"]["answers"]
    assert answers_schema["maxItems"] == 1
    assert answers_schema["items"]["properties"]["question_id"]["enum"] == ["q_001"]
    assert verify_run_report(result.report_path).valid is True
    report_text = (tmp_path / "output" / "ollama_analysis-provider.md").read_text(encoding="utf-8")
    assert "case.txt" in report_text


def test_hallucinated_provider_quote_fails_closed_without_competition_proof(tmp_path) -> None:
    job = make_job(tmp_path)
    provider = ProviderConfig(provider_id="lm-studio", model="local-model")

    result = analyze_with_provider(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        provider,
        run_id="invalid_quote",
        adapter=EvidenceAdapter(provider, bad_quote=True),
    )

    assert result.report.status is RunStatus.FAILED
    assert result.report.errors == ("provider_error:ValueError",)
    assert result.report.metadata["transfer_performed"] is False
    failure = json.loads(
        (tmp_path / "output" / "provider-runs" / "invalid_quote.failure.json").read_text(
            encoding="utf-8"
        )
    )
    assert failure["provider_execution_proof"] is False
    assert failure["competition_proof"] is False


def test_provider_response_identity_and_numeric_contract_fail_closed(tmp_path) -> None:
    job = make_job(tmp_path)
    provider = ProviderConfig(provider_id="ollama", model="qwen3")

    wrong_identity = analyze_with_provider(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        provider,
        run_id="wrong_provider_identity",
        adapter=EvidenceAdapter(provider, provider_id="openai"),
    )
    boolean_uncertainty = analyze_with_provider(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        provider,
        run_id="boolean_uncertainty",
        adapter=EvidenceAdapter(provider, uncertainty=True),
    )

    assert wrong_identity.report.status is RunStatus.FAILED
    assert boolean_uncertainty.report.status is RunStatus.FAILED
    assert wrong_identity.report.metadata["provider_execution_proof"] is False
    assert boolean_uncertainty.report.metadata["provider_execution_proof"] is False


def test_external_provider_requires_server_gate_call_approval_and_allow_once(tmp_path) -> None:
    job = make_job(tmp_path, privacy_mode=PrivacyMode.ALLOW_ONCE, budget=1.0)
    provider = ProviderConfig(
        provider_id="openai",
        model="gpt-5",
        api_key="test-key",
    )

    blocked = analyze_with_provider(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        provider,
        run_id="external_blocked",
        adapter=EvidenceAdapter(provider),
    )

    assert blocked.report.status is RunStatus.BLOCKED
    assert "external_models_disabled" in blocked.report.errors
    assert "external_transfer_not_approved" in blocked.report.errors
    assert "external_budget_exceeds_limit" in blocked.report.errors
    assert blocked.report.metadata["transfer_performed"] is False


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, True])
def test_provider_cost_limit_must_be_finite_and_non_negative(tmp_path, value) -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        ExecutionConfig(
            allowed_roots=(str(tmp_path),),
            external_models_allowed=True,
            max_external_cost_usd=value,
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, True])
def test_provider_job_budget_must_be_finite_and_non_negative(tmp_path, value) -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        make_job(tmp_path, privacy_mode=PrivacyMode.ALLOW_ONCE, budget=value)


def test_external_generic_provider_records_transfer_but_never_competition_proof(tmp_path) -> None:
    job = make_job(tmp_path, privacy_mode=PrivacyMode.ALLOW_ONCE, budget=1.0)
    provider = ProviderConfig(
        provider_id="anthropic",
        model="claude-sonnet-5",
        api_key="test-key",
    )

    result = analyze_with_provider(
        job,
        ExecutionConfig(
            allowed_roots=(str(tmp_path),),
            external_models_allowed=True,
            max_external_cost_usd=1.0,
        ),
        provider,
        run_id="anthropic_analysis",
        approve_external_transfer=True,
        adapter=EvidenceAdapter(provider),
    )

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["transfer_performed"] is True
    assert result.report.metadata["provider_execution_proof"] is True
    assert result.report.metadata["competition_proof"] is False
    assert result.report.metadata["cloud_proof"] is False


def test_external_invalid_response_does_not_hide_the_completed_transfer(tmp_path) -> None:
    job = make_job(tmp_path, privacy_mode=PrivacyMode.ALLOW_ONCE, budget=1.0)
    provider = ProviderConfig(
        provider_id="openai",
        model="gpt-5",
        api_key="test-key",
    )

    result = analyze_with_provider(
        job,
        ExecutionConfig(
            allowed_roots=(str(tmp_path),),
            external_models_allowed=True,
            max_external_cost_usd=1.0,
        ),
        provider,
        run_id="external_invalid",
        approve_external_transfer=True,
        adapter=EvidenceAdapter(provider, bad_quote=True),
    )

    assert result.report.status is RunStatus.FAILED
    assert result.report.metadata["transfer_performed"] is True
    failure = json.loads(
        (tmp_path / "output" / "provider-runs" / "external_invalid.failure.json").read_text(
            encoding="utf-8"
        )
    )
    assert failure["transfer_performed"] is True
    assert failure["raw_response_sha256"] is not None
