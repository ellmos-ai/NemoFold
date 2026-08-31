from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.providers import (
    HTTPExchange,
    ProcessResult,
    ProviderConfig,
    ProviderRequest,
    create_provider,
    provider_capabilities,
    provider_config_from_mapping,
)


class FakeHTTPTransport:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def post(self, url, *, headers, body, timeout_seconds):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "body": json.loads(body),
                "timeout_seconds": timeout_seconds,
            }
        )
        return HTTPExchange(200, {}, json.dumps(self.payload).encode())


class FakeProcessRunner:
    def __init__(self, *, claude: bool = False) -> None:
        self.claude = claude
        self.calls: list[dict] = []

    def run(self, args, *, input_text, cwd, timeout_seconds, env):
        self.calls.append(
            {
                "args": list(args),
                "input": input_text,
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
                "env": dict(env),
            }
        )
        answer = {"answers": [], "unanswered_question_ids": ["q_001"]}
        if self.claude:
            return ProcessResult(0, json.dumps({"structured_output": answer}), "")
        output_index = list(args).index("--output-last-message") + 1
        Path(args[output_index]).write_text(json.dumps(answer), encoding="utf-8")
        return ProcessResult(0, "", "")


def request() -> ProviderRequest:
    return ProviderRequest(
        system_prompt="Use evidence only.",
        user_prompt='{"questions": [{"question_id": "q_001"}]}',
        response_schema={"type": "object"},
    )


def test_capability_registry_keeps_generic_providers_out_of_competition_proof() -> None:
    capabilities = provider_capabilities()

    assert {item["provider_id"] for item in capabilities} == {
        "ollama",
        "lm-studio",
        "codex-cli",
        "claude-code",
        "openai",
        "anthropic",
    }
    assert all(item["competition_proof"] is False for item in capabilities)
    assert (
        next(item for item in capabilities if item["provider_id"] == "ollama")["external_transfer"]
        is False
    )


def test_local_provider_rejects_non_loopback_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        ProviderConfig(
            provider_id="ollama",
            model="qwen3",
            base_url="https://models.example/v1",
        )


def test_provider_mapping_reads_api_keys_only_from_environment() -> None:
    config = provider_config_from_mapping(
        {"provider_id": "openai", "model": "gpt-5"},
        environ={"OPENAI_API_KEY": "secret-from-env"},
    )

    assert config.api_key == "secret-from-env"
    assert "api_key" not in config.public_summary()
    with pytest.raises(ValueError, match="unknown provider field"):
        provider_config_from_mapping(
            {"provider_id": "openai", "model": "gpt-5", "api_key": "in-body"},
            environ={"OPENAI_API_KEY": "secret-from-env"},
        )
    with pytest.raises(ValueError, match="unknown provider field"):
        provider_config_from_mapping(
            {
                "provider_id": "ollama",
                "model": "qwen3",
                "base_url": "http://127.0.0.1:9999/v1",
            }
        )


def test_nebius_is_reserved_for_the_dedicated_competition_path() -> None:
    with pytest.raises(ValueError, match="dedicated token-factory-run"):
        provider_config_from_mapping({"provider_id": "nebius", "model": "nemotron"})


@pytest.mark.parametrize(
    ("provider_id", "base_url"),
    [
        ("ollama", "http://127.0.0.1:11434/v1"),
        ("lm-studio", "http://127.0.0.1:1234/v1"),
    ],
)
def test_local_openai_compatible_adapters_use_only_the_loopback_chat_endpoint(
    provider_id, base_url
) -> None:
    transport = FakeHTTPTransport(
        {
            "id": "local-1",
            "model": "local-model",
            "choices": [{"message": {"content": '{"answers": []}'}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }
    )
    adapter = create_provider(
        ProviderConfig(provider_id=provider_id, model="local-model"),
        http_transport=transport,
    )

    response = adapter.generate(request())

    assert transport.calls[0]["url"] == f"{base_url}/chat/completions"
    assert transport.calls[0]["body"]["response_format"] == {"type": "json_object"}
    assert "Authorization" not in transport.calls[0]["headers"]
    assert response.usage == {"input_tokens": 5, "output_tokens": 2}


def test_openai_adapter_uses_responses_api_and_structured_output() -> None:
    transport = FakeHTTPTransport(
        {
            "id": "resp_1",
            "model": "gpt-5",
            "output": [{"content": [{"type": "output_text", "text": '{"answers": []}'}]}],
            "usage": {"input_tokens": 7, "output_tokens": 3},
        }
    )
    adapter = create_provider(
        ProviderConfig(provider_id="openai", model="gpt-5", api_key="secret"),
        http_transport=transport,
    )

    response = adapter.generate(request())

    call = transport.calls[0]
    assert call["url"] == "https://api.openai.com/v1/responses"
    assert call["body"]["store"] is False
    assert call["body"]["text"]["format"]["type"] == "json_schema"
    assert call["headers"]["Authorization"] == "Bearer secret"
    assert response.request_id == "resp_1"


def test_anthropic_adapter_uses_messages_api_and_structured_output() -> None:
    transport = FakeHTTPTransport(
        {
            "id": "msg_1",
            "model": "claude-sonnet-5",
            "content": [{"type": "text", "text": '{"answers": []}'}],
            "usage": {"input_tokens": 8, "output_tokens": 4},
        }
    )
    adapter = create_provider(
        ProviderConfig(
            provider_id="anthropic",
            model="claude-sonnet-5",
            api_key="secret",
        ),
        http_transport=transport,
    )

    response = adapter.generate(request())

    call = transport.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"]["x-api-key"] == "secret"
    assert call["body"]["output_config"]["format"]["type"] == "json_schema"
    assert response.usage == {"input_tokens": 8, "output_tokens": 4}


@pytest.mark.parametrize(
    ("provider_id", "executable", "claude"),
    [
        ("codex-cli", "codex-test", False),
        ("claude-code", "claude-test", True),
    ],
)
def test_subscription_bridges_use_temporary_read_only_processes_without_api_keys(
    provider_id, executable, claude, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-leak")
    runner = FakeProcessRunner(claude=claude)
    adapter = create_provider(
        ProviderConfig(
            provider_id=provider_id,
            model="subscription-model",
            executable=executable,
        ),
        process_runner=runner,
    )

    response = adapter.generate(request())

    call = runner.calls[0]
    assert call["args"][0] == executable
    assert Path(call["cwd"]).name.startswith("nemofold-provider-cli-")
    assert "OPENAI_API_KEY" not in call["env"]
    assert "ANTHROPIC_API_KEY" not in call["env"]
    assert "UNRELATED_SECRET" not in call["env"]
    assert json.loads(response.text)["unanswered_question_ids"] == ["q_001"]
    if claude:
        assert "--safe-mode" in call["args"]
        assert "--no-session-persistence" in call["args"]
    else:
        assert "--ephemeral" in call["args"]
        assert "--ignore-user-config" in call["args"]
        assert "read-only" in call["args"]
