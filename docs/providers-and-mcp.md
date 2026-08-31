# Provider adapters, local API, and MCP

NemoFold has one evidence-analysis service behind three operator surfaces: CLI,
loopback HTTP, and MCP. All three inventory the same approved roots, build the same
local index, pseudonymize the selected context, and reject a model answer unless every
quote is present in the context sent for that exact question.

## Provider classes

| Provider | Transport | Default boundary | Required approval | Proof class |
|---|---|---|---|---|
| Ollama | OpenAI-compatible HTTP | `127.0.0.1:11434` only | `local_only` job | Generic local execution |
| LM Studio | OpenAI-compatible HTTP | `127.0.0.1:1234` only | `local_only` job | Generic local execution |
| Codex CLI | Temporary headless subprocess | Personal signed-in CLI | server flag, per-call approval, `allow_once` | Generic subscription-CLI execution |
| Claude Code | Temporary headless subprocess | Personal signed-in CLI | server flag, per-call approval, `allow_once` | Generic subscription-CLI execution |
| OpenAI | Responses API | fixed official HTTPS origin | API key environment, budget, server flag, per-call approval, `allow_once` | Generic provider execution |
| Anthropic | Messages API | fixed official HTTPS origin | API key environment, budget, server flag, per-call approval, `allow_once` | Generic provider execution |

The generic registry deliberately contains no Nebius adapter. Nebius/Nemotron remains
the separate `token-factory-preflight` / `token-factory-run` route with its immutable
package, current price inputs, exactly-once transfer attempt, and competition verifier.
A generic provider result always records `competition_proof: false` and
`cloud_proof: false`, even when a transfer and a schema-valid response occurred.

The Codex and Claude bridges are personal test conveniences, not authentication
proxies for a product. They run in a new temporary directory, disable writes and
session persistence, pass only the pseudonymized prompt, invoke an argv array without
a shell, and remove `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from the child environment.
For a multi-user product, use the official provider API adapters instead.

## CLI

List adapters:

```powershell
python -m nemofold providers
```

Run an `evidence_analyst` job through Ollama or LM Studio. The job must omit
`model_id` and use `privacy_mode: local_only`:

```powershell
python -m nemofold analyze-provider --job .\job.json --allow-root C:\Documents `
  --run-id local_qwen --provider ollama --model qwen3

python -m nemofold analyze-provider --job .\job.json --allow-root C:\Documents `
  --run-id local_lm --provider lm-studio --model local-model
```

Use a personal signed-in CLI. The job must use `privacy_mode: allow_once`; both flags
are intentional because the sanitized context may leave the computer:

```powershell
python -m nemofold analyze-provider --job .\job.json --allow-root C:\Documents `
  --run-id codex_personal --provider codex-cli --model <subscription-model> `
  --allow-external-models --approve-external-transfer

python -m nemofold analyze-provider --job .\job.json --allow-root C:\Documents `
  --run-id claude_personal --provider claude-code --model <subscription-model> `
  --allow-external-models --approve-external-transfer
```

Use an official API. API keys are read only from the process environment and are not
accepted in job, HTTP, or MCP payloads. API jobs additionally need a positive, finite
`model_budget_usd` no greater than the finite server-side maximum. The generic receipt records
usage but does not claim that the approved dollar ceiling was independently priced;
the competition Token Factory route is the strict price-bound path.

```powershell
$env:OPENAI_API_KEY = "<session-only-key>"
python -m nemofold analyze-provider --job .\job.json --allow-root C:\Documents `
  --run-id openai_api --provider openai --model <api-model> `
  --allow-external-models --approve-external-transfer --max-external-cost-usd 1
Remove-Item Env:\OPENAI_API_KEY
```

## MCP for Codex CLI and Claude Code

The MCP server uses stdio, writes protocol messages only through the official MCP SDK,
and receives its filesystem authority when the operator starts it:

```powershell
codex mcp add nemofold -- python -m nemofold mcp `
  --base-dir C:\Documents --allow-root C:\Documents

claude mcp add --scope user nemofold -- python -m nemofold mcp `
  --base-dir C:\Documents --allow-root C:\Documents
```

This exposes six typed tools:

- `nemofold_capabilities`
- `nemofold_anonymize`
- `nemofold_preview`
- `nemofold_run`
- `nemofold_analyze_with_provider`
- `nemofold_verify_report`

External model use remains disabled unless the MCP process itself was started with
`--allow-external-models` and a call also sets `approve_external_transfer: true`.
File actions remain disabled unless the process was started with `--approve-actions`.
The job contract still enforces `allow_once`, paths, budget, and workflow constraints.

## Loopback HTTP API

`nemofold serve` exposes the same service at `POST /api/provider-analyze`. The request
contains `run_id`, `job`, a non-secret `provider` object, and the per-call approval.
`GET /api/status` lists the configured adapter contracts. API keys are environment-only.
`provider_surface_enabled` reports only whether the route is available;
`provider_runtime_ready` remains false until a real provider health/execution check exists.
The provider route is available only while the regular server remains loopback-only.
It is disabled when `--expose-network` is active, and the capability-minimal
`serve-demo` surface does not expose it at all.

Example provider object:

```json
{
  "provider_id": "ollama",
  "model": "qwen3",
  "max_output_tokens": 1200,
  "timeout_seconds": 60
}
```

## Upstream contracts

- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Anthropic Messages API](https://platform.claude.com/docs/en/api/http/messages/create)
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- [LM Studio REST API](https://lmstudio.ai/docs/developer/rest)
- [Codex CLI](https://learn.chatgpt.com/docs/codex/cli)
- [Claude Code headless mode](https://code.claude.com/docs/en/headless)
