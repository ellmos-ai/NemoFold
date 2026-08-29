from __future__ import annotations

from collections.abc import Mapping

from .contracts import Claim, EvidenceLocator, JobEnvelope
from .runtime import ReasoningResult


class DeterministicDemoReasoner:
    """Offline fixture adapter. It is evidence, but explicitly not cloud proof."""

    adapter_id = "deterministic_demo"
    target_quote = "Coverage begins on 1 April 2026."

    def analyze(
        self,
        job: JobEnvelope,
        source_texts: Mapping[str, str],
    ) -> ReasoningResult:
        del job
        for source_id, text in source_texts.items():
            if self.target_quote in text:
                return ReasoningResult(
                    claims=(
                        Claim(
                            statement="The current synthetic policy begins on 1 April 2026.",
                            evidence=(
                                EvidenceLocator(
                                    source_id=source_id,
                                    quote=self.target_quote,
                                    section="Policy period",
                                ),
                            ),
                        ),
                    ),
                    read_source_ids=(source_id,),
                )
        return ReasoningResult(
            claims=(Claim(statement="No supported policy start date was found."),),
            read_source_ids=tuple(source_texts),
        )
