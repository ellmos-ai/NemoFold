"""Let a reasoning worker choose the workflows for a captain request.

The worker sees the request sentence and the workflow catalogue, never a
document. Its answer is checked against the catalogue, and the plan itself is
then built by the same planner as a keyword match, so a model can choose
steps but never invent one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from .anonymizer import detect_sensitive_categories, pseudonymize_text
from .providers import ProviderAdapter, ProviderConfig, ProviderRequest, create_provider
from .wizard import WORKFLOW_ORDER, WORKFLOW_TITLES, workflow_purpose

MAX_PLANNED_STEPS = 6

SYSTEM_PROMPT = (
    "You plan work for NemoFold, a local document workspace. Choose the workflows "
    "that fulfil the person's request, in the order they should run, at most "
    f"{MAX_PLANNED_STEPS}. Use only workflow ids from the catalogue below; if none "
    "fits, return an empty list. Answer with JSON only: "
    '{"workflows": ["<id>", ...], "reason": "<one sentence>"}.\n\nCatalogue:\n'
)


def plan_with_model(
    text: str,
    config: ProviderConfig,
    *,
    create: Callable[[ProviderConfig], ProviderAdapter] = create_provider,
) -> tuple[tuple[str, ...], str]:
    """Return the chosen workflow ids and the worker's one-sentence reason."""
    request = " ".join(text.split())
    if not request:
        raise ValueError("request text must not be empty")
    if config.descriptor.external_transfer:
        # The sentence leaves this computer, so it goes pseudonymized, and a
        # sentence that still carries a sensitive category does not go at all.
        request = pseudonymize_text(request).text
        leftover = detect_sensitive_categories(request)
        if leftover:
            raise ValueError(
                "the request still carries " + ", ".join(leftover) + " after pseudonymization"
            )
    catalogue = "\n".join(
        f"- {workflow}: {WORKFLOW_TITLES[workflow]}. {workflow_purpose(workflow)}"
        for workflow in sorted(WORKFLOW_ORDER, key=lambda item: WORKFLOW_ORDER[item])
    )
    schema = {
        "type": "object",
        "properties": {
            "workflows": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(WORKFLOW_ORDER)},
                "maxItems": MAX_PLANNED_STEPS,
            },
            "reason": {"type": "string"},
        },
        "required": ["workflows", "reason"],
        "additionalProperties": False,
    }
    response = create(config).generate(
        ProviderRequest(
            system_prompt=SYSTEM_PROMPT + catalogue,
            user_prompt=request,
            response_schema=schema,
        )
    )
    answer = _json_object(response.text)
    raw = answer.get("workflows")
    if not isinstance(raw, list):
        raise ValueError("the model answer carries no workflow list")
    chosen = tuple(
        dict.fromkeys(item for item in raw if isinstance(item, str) and item in WORKFLOW_ORDER)
    )[:MAX_PLANNED_STEPS]
    if not chosen:
        raise ValueError("the model chose no known workflow for this request")
    reason = answer.get("reason")
    return chosen, " ".join(reason.split())[:400] if isinstance(reason, str) else ""


def _json_object(text: str) -> dict[str, object]:
    """The JSON object in a reply, also when a small model wraps it in prose."""
    try:
        value = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match is None:
            raise ValueError("the model did not answer with JSON") from None
        try:
            value = json.loads(match.group(0))
        except ValueError:
            raise ValueError("the model did not answer with JSON") from None
    if not isinstance(value, dict):
        raise ValueError("the model did not answer with a JSON object")
    return value
