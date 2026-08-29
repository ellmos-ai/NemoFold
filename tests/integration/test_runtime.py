from __future__ import annotations

from dataclasses import replace

from nemofold.contracts import (
    ActionMode,
    Claim,
    EvidenceLocator,
    JobEnvelope,
    PrivacyMode,
    RunStatus,
    SourceRecord,
)
from nemofold.ledger import RunLedger
from nemofold.policy import PolicyConfig, PolicyGate
from nemofold.runtime import LocalAgentRuntime, ReasoningResult


class FixedReasoner:
    def __init__(self, result: ReasoningResult) -> None:
        self.result = result
        self.called = False

    def analyze(self, job, source_texts) -> ReasoningResult:
        self.called = True
        return self.result


def make_job_and_sources(tmp_path):
    root = tmp_path / "approved"
    root.mkdir()
    output = root / "out"
    first = SourceRecord(
        source_id="src_a",
        path=str(root / "a.txt"),
        display_name="a.txt",
        sha256="a" * 64,
        mime_type="text/plain",
    )
    second = SourceRecord(
        source_id="src_b",
        path=str(root / "b.txt"),
        display_name="b.txt",
        sha256="b" * 64,
        mime_type="text/plain",
    )
    job = JobEnvelope(
        workflow="evidence_analyst",
        input_roots=(str(root),),
        output_dir=str(output),
        questions=("What is confirmed?",),
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        action_mode=ActionMode.DRY_RUN,
        sources=(first, second),
    )
    return job, {"src_a": "The confirmed value is 42.", "src_b": "Background only."}


def test_runtime_executes_and_records_coverage(tmp_path) -> None:
    job, source_texts = make_job_and_sources(tmp_path)
    reasoner = FixedReasoner(
        ReasoningResult(
            claims=(
                Claim(
                    statement="The value is 42.",
                    evidence=(EvidenceLocator(source_id="src_a", quote="value is 42"),),
                ),
            ),
            read_source_ids=("src_a",),
        )
    )
    ledger = RunLedger(tmp_path / "ledger")
    runtime = LocalAgentRuntime(
        gate=PolicyGate(PolicyConfig(allowed_roots=job.input_roots)),
        ledger=ledger,
    )

    result = runtime.execute(job, reasoner, source_texts, run_id="run_good")

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.coverage.unread_source_ids == ("src_b",)
    assert result.validations[0].verified is True
    assert ledger.load("run_good") == result.report


def test_runtime_blocks_before_reasoner_when_external_use_is_not_approved(tmp_path) -> None:
    job, source_texts = make_job_and_sources(tmp_path)
    external_job = replace(job, model_id="nvidia/nemotron")
    reasoner = FixedReasoner(ReasoningResult(claims=(), read_source_ids=()))
    runtime = LocalAgentRuntime(
        gate=PolicyGate(
            PolicyConfig(
                allowed_roots=job.input_roots,
                external_models_allowed=True,
                max_external_cost_usd=1.0,
            )
        ),
        ledger=RunLedger(tmp_path / "ledger"),
    )

    result = runtime.execute(external_job, reasoner, source_texts, run_id="run_blocked")

    assert result.report.status is RunStatus.BLOCKED
    assert "external_privacy_not_approved" in result.report.errors
    assert reasoner.called is False


def test_runtime_fails_closed_on_unverifiable_claim(tmp_path) -> None:
    job, source_texts = make_job_and_sources(tmp_path)
    reasoner = FixedReasoner(
        ReasoningResult(
            claims=(
                Claim(
                    statement="Invented",
                    evidence=(EvidenceLocator(source_id="src_a", quote="not in source"),),
                ),
            ),
            read_source_ids=("src_a",),
        )
    )
    runtime = LocalAgentRuntime(
        gate=PolicyGate(PolicyConfig(allowed_roots=job.input_roots)),
        ledger=RunLedger(tmp_path / "ledger"),
    )

    result = runtime.execute(job, reasoner, source_texts, run_id="run_invalid")

    assert result.report.status is RunStatus.FAILED
    assert "unverified_claim:0" in result.report.errors
