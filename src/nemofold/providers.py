from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_PROVIDER_RESPONSE_BYTES = 4 * 1024 * 1024


class ProviderTransport(StrEnum):
    LOCAL_HTTP = "local_http"
    PROVIDER_API = "provider_api"
    SUBSCRIPTION_CLI = "subscription_cli"


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider_id: str
    label: str
    transport: ProviderTransport
    external_transfer: bool
    competition_proof: bool = False
    default_base_url: str | None = None
    api_key_env: str | None = None


PROVIDER_DESCRIPTORS: dict[str, ProviderDescriptor] = {
    "ollama": ProviderDescriptor(
        provider_id="ollama",
        label="Ollama (local)",
        transport=ProviderTransport.LOCAL_HTTP,
        external_transfer=False,
        default_base_url="http://127.0.0.1:11434/v1",
    ),
    "lm-studio": ProviderDescriptor(
        provider_id="lm-studio",
        label="LM Studio (local)",
        transport=ProviderTransport.LOCAL_HTTP,
        external_transfer=False,
        default_base_url="http://127.0.0.1:1234/v1",
    ),
    "codex-cli": ProviderDescriptor(
        provider_id="codex-cli",
        label="Codex CLI personal bridge",
        transport=ProviderTransport.SUBSCRIPTION_CLI,
        external_transfer=True,
    ),
    "claude-code": ProviderDescriptor(
        provider_id="claude-code",
        label="Claude Code personal bridge",
        transport=ProviderTransport.SUBSCRIPTION_CLI,
        external_transfer=True,
    ),
    "openai": ProviderDescriptor(
        provider_id="openai",
        label="OpenAI Responses API",
        transport=ProviderTransport.PROVIDER_API,
        external_transfer=True,
        default_base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
    ),
    "anthropic": ProviderDescriptor(
        provider_id="anthropic",
        label="Anthropic Messages API",
        transport=ProviderTransport.PROVIDER_API,
        external_transfer=True,
        default_base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
    ),
}


def provider_capabilities() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "provider_id": descriptor.provider_id,
            "label": descriptor.label,
            "transport": descriptor.transport.value,
            "external_transfer": descriptor.external_transfer,
            "competition_proof": descriptor.competition_proof,
            "default_base_url": descriptor.default_base_url,
            "api_key_env": descriptor.api_key_env,
        }
        for descriptor in PROVIDER_DESCRIPTORS.values()
    )


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    provider_id: str
    model: str
    base_url: str | None = None
    max_output_tokens: int = 1200
    timeout_seconds: float = 60.0
    executable: str | None = None
    api_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.provider_id not in PROVIDER_DESCRIPTORS:
            raise ValueError(f"unsupported provider: {self.provider_id}")
        if not self.model.strip():
            raise ValueError("provider model must not be blank")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or not 1 <= self.max_output_tokens <= 65_536
        ):
            raise ValueError("max_output_tokens must be between 1 and 65536")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 1 <= self.timeout_seconds <= 600
        ):
            raise ValueError("timeout_seconds must be between 1 and 600")
        descriptor = self.descriptor
        if descriptor.transport is ProviderTransport.LOCAL_HTTP:
            _validated_local_base_url(self.base_url or descriptor.default_base_url or "")
        elif self.base_url not in {None, descriptor.default_base_url}:
            raise ValueError("cloud API base_url cannot be overridden")
        if descriptor.api_key_env and not (self.api_key or "").strip():
            raise ValueError(f"{descriptor.api_key_env} is missing")
        if self.executable is not None and not self.executable.strip():
            raise ValueError("provider executable must not be blank")

    @property
    def descriptor(self) -> ProviderDescriptor:
        return PROVIDER_DESCRIPTORS[self.provider_id]

    @property
    def resolved_base_url(self) -> str | None:
        return (self.base_url or self.descriptor.default_base_url or "").rstrip("/") or None

    def public_summary(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "model": self.model,
            "transport": self.descriptor.transport.value,
            "external_transfer": self.descriptor.external_transfer,
            "competition_proof": False,
            "base_url": self.resolved_base_url,
            "max_output_tokens": self.max_output_tokens,
            "timeout_seconds": self.timeout_seconds,
        }


def provider_config_from_mapping(
    value: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
    allow_runtime_overrides: bool = False,
) -> ProviderConfig:
    allowed = {
        "provider_id",
        "model",
        "max_output_tokens",
        "timeout_seconds",
    }
    if allow_runtime_overrides:
        allowed.update({"base_url", "executable"})
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown provider field: {unknown[0]}")
    provider_id = value.get("provider_id")
    model = value.get("model")
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise ValueError("provider_id must be a non-empty string")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("provider model must be a non-empty string")
    descriptor = PROVIDER_DESCRIPTORS.get(provider_id)
    if descriptor is None:
        if provider_id == "nebius" or provider_id.startswith("nemotron"):
            raise ValueError("Nebius/Nemotron uses the dedicated token-factory-run proof path")
        raise ValueError(f"unsupported provider: {provider_id}")
    env = os.environ if environ is None else environ
    api_key = env.get(descriptor.api_key_env, "") if descriptor.api_key_env else None
    base_url = value.get("base_url")
    executable = value.get("executable")
    if base_url is not None and not isinstance(base_url, str):
        raise ValueError("base_url must be a string")
    if executable is not None and not isinstance(executable, str):
        raise ValueError("executable must be a string")
    return ProviderConfig(
        provider_id=provider_id,
        model=model,
        base_url=base_url,
        max_output_tokens=value.get("max_output_tokens", 1200),
        timeout_seconds=value.get("timeout_seconds", 60.0),
        executable=executable,
        api_key=api_key,
    )


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    system_prompt: str
    user_prompt: str
    response_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    text: str
    provider_id: str
    model: str
    usage: dict[str, int]
    request_id: str | None = None


class ProviderAdapter(Protocol):
    config: ProviderConfig

    def generate(self, request: ProviderRequest) -> ProviderResponse: ...


@dataclass(frozen=True, slots=True)
class HTTPExchange:
    status: int
    headers: dict[str, str]
    body: bytes


class HTTPTransport(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> HTTPExchange: ...


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        return None


class UrllibHTTPTransport:
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> HTTPExchange:
        request = Request(url, data=body, headers=headers, method="POST")
        opener = build_opener(_RejectRedirects())
        try:
            response = opener.open(request, timeout=timeout_seconds)  # noqa: S310
        except HTTPError as exc:
            response = exc
        with response:
            content = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
            if len(content) > MAX_PROVIDER_RESPONSE_BYTES:
                raise RuntimeError("provider response exceeds the size limit")
            return HTTPExchange(
                status=int(response.status),
                headers={str(key).casefold(): str(item) for key, item in response.headers.items()},
                body=content,
            )


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class ProcessRunner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        input_text: str,
        cwd: str,
        timeout_seconds: float,
        env: Mapping[str, str],
    ) -> ProcessResult: ...


class SubprocessRunner:
    def run(
        self,
        args: Sequence[str],
        *,
        input_text: str,
        cwd: str,
        timeout_seconds: float,
        env: Mapping[str, str],
    ) -> ProcessResult:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        completed = subprocess.run(  # noqa: S603 - argv only, no shell
            list(args),
            input=input_text,
            text=True,
            capture_output=True,
            cwd=cwd,
            env=dict(env),
            timeout=timeout_seconds,
            check=False,
            creationflags=creationflags,
        )
        return ProcessResult(completed.returncode, completed.stdout, completed.stderr)


def _validated_local_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/", "/v1", "/v1/"}
    ):
        raise ValueError("local provider base_url must be a loopback HTTP URL")
    return value.rstrip("/")


def _json_body(exchange: HTTPExchange) -> dict[str, Any]:
    if not 200 <= exchange.status < 300:
        raise RuntimeError(f"provider HTTP status {exchange.status}")
    try:
        payload = json.loads(exchange.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("provider returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("provider response root must be an object")
    return payload


def _usage(value: Any, *, input_key: str, output_key: str) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for target, source in (("input_tokens", input_key), ("output_tokens", output_key)):
        item = value.get(source)
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
            result[target] = item
    return result


def _request_prompt(request: ProviderRequest) -> str:
    return (
        f"{request.system_prompt}\n\n"
        "Return only one JSON object matching this schema:\n"
        f"{json.dumps(request.response_schema, sort_keys=True)}\n\n"
        f"Input:\n{request.user_prompt}"
    )


def _safe_cli_environment() -> dict[str, str]:
    allowed = {
        "APPDATA",
        "CLAUDE_CONFIG_DIR",
        "CODEX_HOME",
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


class OpenAICompatibleAdapter:
    def __init__(self, config: ProviderConfig, transport: HTTPTransport) -> None:
        self.config = config
        self.transport = transport

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        base_url = _validated_local_base_url(self.config.resolved_base_url or "")
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": 0,
            "max_tokens": self.config.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "nemofold_provider_analysis",
                    "strict": True,
                    "schema": request.response_schema,
                },
            },
        }
        if self.config.provider_id == "ollama":
            # Evidence extraction benefits from bounded deterministic output, not a
            # hidden reasoning trace. Ollama documents `none` for thinking control
            # on its OpenAI-compatible chat-completions endpoint.
            payload["reasoning_effort"] = "none"
        body = json.dumps(payload).encode()
        exchange = self.transport.post(
            f"{base_url}/chat/completions",
            headers={"Content-Type": "application/json"},
            body=body,
            timeout_seconds=self.config.timeout_seconds,
        )
        payload = _json_body(exchange)
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenAI-compatible response has no message content") from exc
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("OpenAI-compatible response text is empty")
        return ProviderResponse(
            text=text,
            provider_id=self.config.provider_id,
            model=str(payload.get("model") or self.config.model),
            usage=_usage(
                payload.get("usage"),
                input_key="prompt_tokens",
                output_key="completion_tokens",
            ),
            request_id=str(payload["id"]) if isinstance(payload.get("id"), str) else None,
        )


class OpenAIResponsesAdapter:
    def __init__(self, config: ProviderConfig, transport: HTTPTransport) -> None:
        self.config = config
        self.transport = transport

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        body = json.dumps(
            {
                "model": self.config.model,
                "instructions": request.system_prompt,
                "input": request.user_prompt,
                "max_output_tokens": self.config.max_output_tokens,
                "store": False,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "nemofold_provider_analysis",
                        "schema": request.response_schema,
                        "strict": True,
                    }
                },
            }
        ).encode()
        exchange = self.transport.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            body=body,
            timeout_seconds=self.config.timeout_seconds,
        )
        payload = _json_body(exchange)
        texts: list[str] = []
        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                content = item.get("content") if isinstance(item, dict) else None
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "output_text":
                        text = block.get("text")
                        if isinstance(text, str):
                            texts.append(text)
        if not texts:
            raise RuntimeError("OpenAI response has no output_text content")
        return ProviderResponse(
            text="".join(texts),
            provider_id=self.config.provider_id,
            model=str(payload.get("model") or self.config.model),
            usage=_usage(
                payload.get("usage"), input_key="input_tokens", output_key="output_tokens"
            ),
            request_id=str(payload["id"]) if isinstance(payload.get("id"), str) else None,
        )


class AnthropicMessagesAdapter:
    def __init__(self, config: ProviderConfig, transport: HTTPTransport) -> None:
        self.config = config
        self.transport = transport

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        body = json.dumps(
            {
                "model": self.config.model,
                "max_tokens": self.config.max_output_tokens,
                "system": request.system_prompt,
                "messages": [{"role": "user", "content": request.user_prompt}],
                "output_config": {
                    "format": {"type": "json_schema", "schema": request.response_schema}
                },
            }
        ).encode()
        exchange = self.transport.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": str(self.config.api_key),
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            body=body,
            timeout_seconds=self.config.timeout_seconds,
        )
        payload = _json_body(exchange)
        content = payload.get("content")
        texts = (
            [
                item["text"]
                for item in content
                if isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ]
            if isinstance(content, list)
            else []
        )
        if not texts:
            raise RuntimeError("Anthropic response has no text content")
        return ProviderResponse(
            text="".join(texts),
            provider_id=self.config.provider_id,
            model=str(payload.get("model") or self.config.model),
            usage=_usage(
                payload.get("usage"), input_key="input_tokens", output_key="output_tokens"
            ),
            request_id=str(payload["id"]) if isinstance(payload.get("id"), str) else None,
        )


class SubscriptionCLIAdapter:
    def __init__(self, config: ProviderConfig, runner: ProcessRunner) -> None:
        self.config = config
        self.runner = runner

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        prompt = _request_prompt(request)
        safe_env = _safe_cli_environment()
        with TemporaryDirectory(prefix="nemofold-provider-cli-") as temporary:
            root = Path(temporary)
            schema_path = root / "response-schema.json"
            schema_path.write_text(json.dumps(request.response_schema), encoding="utf-8")
            if self.config.provider_id == "codex-cli":
                output_path = root / "last-message.json"
                args = [
                    self.config.executable or "codex",
                    "exec",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--disable",
                    "shell_tool",
                    "--disable",
                    "apps",
                    "--disable",
                    "browser_use",
                    "--disable",
                    "computer_use",
                    "--disable",
                    "image_generation",
                    "--disable",
                    "hooks",
                    "--disable",
                    "memories",
                    "--disable",
                    "plugins",
                    "--disable",
                    "skill_search",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "--color",
                    "never",
                    "--output-schema",
                    str(schema_path),
                    "--output-last-message",
                    str(output_path),
                ]
                if self.config.model:
                    args.extend(("--model", self.config.model))
                args.append("-")
                completed = self.runner.run(
                    args,
                    input_text=prompt,
                    cwd=temporary,
                    timeout_seconds=self.config.timeout_seconds,
                    env=safe_env,
                )
                if completed.returncode != 0:
                    raise RuntimeError("Codex CLI provider failed")
                try:
                    text = output_path.read_text(encoding="utf-8")
                except OSError as exc:
                    raise RuntimeError("Codex CLI did not write its final response") from exc
            else:
                args = [
                    self.config.executable or "claude",
                    "--print",
                    "--safe-mode",
                    "--no-session-persistence",
                    "--permission-mode",
                    "dontAsk",
                    "--tools",
                    "",
                    "--output-format",
                    "json",
                    "--json-schema",
                    json.dumps(request.response_schema, separators=(",", ":")),
                    "--model",
                    self.config.model,
                ]
                completed = self.runner.run(
                    args,
                    input_text=prompt,
                    cwd=temporary,
                    timeout_seconds=self.config.timeout_seconds,
                    env=safe_env,
                )
                if completed.returncode != 0:
                    raise RuntimeError("Claude Code provider failed")
                try:
                    envelope = json.loads(completed.stdout)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Claude Code returned invalid JSON") from exc
                if not isinstance(envelope, dict):
                    raise RuntimeError("Claude Code response root must be an object")
                structured = envelope.get("structured_output")
                if isinstance(structured, dict):
                    text = json.dumps(structured)
                elif isinstance(envelope.get("result"), str):
                    text = envelope["result"]
                else:
                    raise RuntimeError("Claude Code response has no structured output")
        if not text.strip():
            raise RuntimeError("subscription CLI response is empty")
        return ProviderResponse(
            text=text,
            provider_id=self.config.provider_id,
            model=self.config.model,
            usage={},
        )


def create_provider(
    config: ProviderConfig,
    *,
    http_transport: HTTPTransport | None = None,
    process_runner: ProcessRunner | None = None,
) -> ProviderAdapter:
    descriptor = config.descriptor
    if descriptor.transport is ProviderTransport.LOCAL_HTTP:
        return OpenAICompatibleAdapter(config, http_transport or UrllibHTTPTransport())
    if config.provider_id == "openai":
        return OpenAIResponsesAdapter(config, http_transport or UrllibHTTPTransport())
    if config.provider_id == "anthropic":
        return AnthropicMessagesAdapter(config, http_transport or UrllibHTTPTransport())
    return SubscriptionCLIAdapter(config, process_runner or SubprocessRunner())
