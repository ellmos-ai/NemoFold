"""K12/K13: asking back properly, and checking a bundle before it is believed.

Two small contracts that both exist because "it ran" is not the same as "it is
usable".

**needs_user_input** is a structured outcome, not a sentence in a log. A question
names the field it is about, says why it is being asked and what shape an answer
takes, so a surface can render it as a form and a chain can stop at exactly the
right step. A workflow that guesses at a missing field produces a result nobody
can check; a workflow that fails silently produces one nobody can fix.

**bundle_completeness_check** is the step you put in front of trusting a bundle.
It reports, from coverage alone, whether every approved source was actually read,
whether the formats a later step needs can be produced, and whether any required
part came out empty. It concludes nothing about content - it only says whether
the material is complete enough for the next step to mean anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

QUESTION_KINDS = ("text", "path", "choice", "confirmation", "address")
MAX_QUESTIONS = 20
MAX_PROMPT_CHARS = 400


@dataclass(frozen=True, slots=True)
class Question:
    """One thing a run needs from a person before it can honestly continue."""

    field: str
    prompt: str
    why: str
    kind: str = "text"
    choices: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "field": self.field,
            "prompt": self.prompt,
            "why": self.why,
            "kind": self.kind,
        }
        if self.choices:
            payload["choices"] = list(self.choices)
        return payload


def validate_question(value: Any) -> Question:
    if not isinstance(value, dict) or set(value) - {
        "field", "prompt", "why", "kind", "choices"
    }:
        raise ValueError("a question holds only field, prompt, why, kind and choices")
    field = str(value.get("field", "")).strip()
    prompt = str(value.get("prompt", "")).strip()
    if not field or not prompt:
        raise ValueError("a question needs the field it is about and a prompt")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"a prompt may not exceed {MAX_PROMPT_CHARS} characters")
    kind = str(value.get("kind", "text"))
    if kind not in QUESTION_KINDS:
        raise ValueError(f"question kind must be one of {', '.join(QUESTION_KINDS)}")
    choices = value.get("choices") or ()
    if not isinstance(choices, (list, tuple)):
        raise ValueError("choices must be a list")
    if kind == "choice" and not choices:
        raise ValueError("a choice question needs its choices")
    return Question(
        field=field,
        prompt=prompt,
        why=str(value.get("why", "")).strip(),
        kind=kind,
        choices=tuple(str(item) for item in choices),
    )


def needs_input_payload(questions: tuple[Question, ...], *, workflow: str) -> dict[str, object]:
    """The structured outcome a surface renders and a chain stops on."""
    if len(questions) > MAX_QUESTIONS:
        raise ValueError(f"a run may not ask more than {MAX_QUESTIONS} questions at once")
    return {
        "schema": "nemofold.needs-user-input.v1",
        "workflow": workflow,
        "question_count": len(questions),
        "questions": [item.as_payload() for item in questions],
        "outcome_note": (
            "This run stopped because it would otherwise have guessed. Nothing was "
            "written beyond this request, and answering these fields is enough to "
            "continue."
        ),
    }


# --------------------------------------------------------------------------- #
# Completeness
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CompletenessFinding:
    check: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class CompletenessReport:
    findings: tuple[CompletenessFinding, ...]

    @property
    def complete(self) -> bool:
        return all(item.passed for item in self.findings)

    @property
    def failed(self) -> tuple[CompletenessFinding, ...]:
        return tuple(item for item in self.findings if not item.passed)


def check_completeness(
    *,
    total_sources: int,
    read_sources: int,
    unread_source_ids: tuple[str, ...],
    required_formats: tuple[str, ...],
    available_formats: tuple[str, ...],
    required_parts: dict[str, int],
) -> CompletenessReport:
    """Say whether this material is complete enough for a next step to mean anything.

    Every check reports both ways. A passing check that says nothing is as
    useless as a failing one that says only "incomplete", because the reader
    needs to know what was verified, not only what broke.
    """
    findings: list[CompletenessFinding] = []
    if total_sources == 0:
        findings.append(
            CompletenessFinding("sources_read", False, "no approved source was found at all")
        )
    else:
        passed = read_sources == total_sources
        findings.append(
            CompletenessFinding(
                "sources_read",
                passed,
                f"{read_sources} of {total_sources} source(s) were read"
                + (
                    ""
                    if passed
                    else f"; unread: {', '.join(unread_source_ids[:10]) or 'unnamed'}"
                ),
            )
        )
    missing_formats = [item for item in required_formats if item not in available_formats]
    findings.append(
        CompletenessFinding(
            "formats_available",
            not missing_formats,
            "every required format can be produced"
            if not missing_formats
            else f"cannot produce: {', '.join(missing_formats)}",
        )
    )
    empty = sorted(name for name, count in required_parts.items() if count <= 0)
    findings.append(
        CompletenessFinding(
            "required_parts_filled",
            not empty,
            "every required part carries content"
            if not empty
            else f"empty required part(s): {', '.join(empty)}",
        )
    )
    return CompletenessReport(findings=tuple(findings))


def completeness_payload(report: CompletenessReport) -> dict[str, object]:
    return {
        "schema": "nemofold.completeness.v1",
        "complete": report.complete,
        "failed_count": len(report.failed),
        "checks": [
            {"check": item.check, "passed": item.passed, "detail": item.detail}
            for item in report.findings
        ],
        "scope_note": (
            "This check is about the material, not about what it says. It reports "
            "whether every source was read, whether the required formats can be "
            "produced and whether a required part came out empty. It concludes "
            "nothing about content."
        ),
    }
