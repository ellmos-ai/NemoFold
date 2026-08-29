from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Protocol

from .contracts import (
    Claim,
    ClaimValidation,
    JobEnvelope,
    RunReport,
    RunStatus,
    to_primitive,
)
from .evidence import compute_coverage, validate_claim
from .ledger import RunLedger
from .policy import PolicyGate


@dataclass(frozen=True, slots=True)
class ReasoningResult:
    claims: tuple[Claim, ...]
    read_source_ids: tuple[str, ...]


class ReasoningPort(Protocol):
    def analyze(
        self,
        job: JobEnvelope,
        source_texts: Mapping[str, str],
    ) -> ReasoningResult: ...


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    report: RunReport
    claims: tuple[Claim, ...]
    validations: tuple[ClaimValidation, ...]


def job_idempotency_key(job: JobEnvelope) -> str:
    encoded = json.dumps(to_primitive(job), sort_keys=True, separators=(",", ":")).encode()
    return f"job_{hashlib.sha256(encoded).hexdigest()}"


class LocalAgentRuntime:
    def __init__(self, *, gate: PolicyGate, ledger: RunLedger) -> None:
        self.gate = gate
        self.ledger = ledger

    def execute(
        self,
        job: JobEnvelope,
        reasoner: ReasoningPort,
        source_texts: Mapping[str, str],
        *,
        run_id: str,
    ) -> RuntimeResult:
        decision = self.gate.evaluate(job)
        initial = RunReport(
            run_id=run_id,
            idempotency_key=job_idempotency_key(job),
            workflow=job.workflow,
            status=RunStatus.PLANNED if decision.allowed else RunStatus.BLOCKED,
            errors=decision.reasons,
            gate_decision=decision,
        )
        self.ledger.save(initial)
        if not decision.allowed:
            return RuntimeResult(report=initial, claims=(), validations=())

        running = self.ledger.transition(run_id, RunStatus.RUNNING)
        try:
            reasoning = reasoner.analyze(job, source_texts)
        except Exception as exc:  # adapters are intentionally a fail-closed boundary
            failed = replace(
                running,
                status=RunStatus.FAILED,
                errors=(f"reasoner_error:{type(exc).__name__}",),
            )
            self.ledger.update(failed)
            return RuntimeResult(report=failed, claims=(), validations=())

        validations = tuple(validate_claim(claim, source_texts) for claim in reasoning.claims)
        verified_claims = tuple(
            claim for claim, validation in zip(reasoning.claims, validations, strict=True)
            if validation.verified
        )
        cited_ids = {
            locator.source_id
            for claim in verified_claims
            for locator in claim.evidence
        }
        coverage = compute_coverage(
            all_source_ids=(source.source_id for source in job.sources),
            read_source_ids=reasoning.read_source_ids,
            cited_source_ids=cited_ids,
        )
        errors = tuple(
            f"unverified_claim:{index}"
            for index, validation in enumerate(validations)
            if not validation.verified
        )
        final = replace(
            running,
            status=RunStatus.FAILED if errors else RunStatus.EXECUTED,
            actions=("reasoning_completed", "claims_validated"),
            errors=errors,
            coverage=coverage,
            metadata={
                "claim_count": len(reasoning.claims),
                "reasoning_adapter": getattr(reasoner, "adapter_id", type(reasoner).__name__),
            },
        )
        self.ledger.update(final)
        return RuntimeResult(report=final, claims=reasoning.claims, validations=validations)
