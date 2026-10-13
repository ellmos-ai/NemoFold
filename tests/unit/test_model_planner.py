from __future__ import annotations

import pytest

from nemofold.model_planner import plan_with_model
from nemofold.providers import ProviderResponse, provider_config_from_mapping


class FakeWorker:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list = []

    def generate(self, request):
        self.requests.append(request)
        return ProviderResponse(text=self.text, provider_id="fake", model="fake", usage={})


def test_the_model_chooses_from_the_catalogue_only() -> None:
    worker = FakeWorker(
        'Here you go: {"workflows": ["fact_distill", "made_up", "fact_distill", '
        '"evidence_analyst"], "reason": "facts first, then answers"}'
    )
    config = provider_config_from_mapping({"provider_id": "ollama", "model": "qwen3.8:27b-mlx"})

    chosen, reason = plan_with_model("Fasse die Akten zusammen", config, create=lambda _: worker)

    assert chosen == ("fact_distill", "evidence_analyst")
    assert reason == "facts first, then answers"
    request = worker.requests[0]
    assert "- evidence_analyst:" in request.system_prompt
    assert request.user_prompt == "Fasse die Akten zusammen"


def test_an_external_planner_gets_the_sentence_pseudonymized() -> None:
    worker = FakeWorker('{"workflows": ["evidence_analyst"], "reason": "one question"}')
    config = provider_config_from_mapping(
        {"provider_id": "nebius", "model": "nvidia/nemotron-3-super-120b-a12b"},
        environ={"NEBIUS_API_KEY": "test-key"},
    )

    plan_with_model("Ruf mich an unter 0761 1234567", config, create=lambda _: worker)

    assert "1234567" not in worker.requests[0].user_prompt


def test_a_model_that_chooses_nothing_known_is_refused() -> None:
    worker = FakeWorker('{"workflows": ["delete_everything"], "reason": "x"}')
    config = provider_config_from_mapping({"provider_id": "ollama", "model": "qwen3:4b"})

    with pytest.raises(ValueError, match="no known workflow"):
        plan_with_model("Räum alles auf", config, create=lambda _: worker)
