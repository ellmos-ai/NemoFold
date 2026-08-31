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

For deterministic evidence extraction, the Ollama adapter sets the documented
OpenAI-compatible `reasoning_effort: none`; this prevents thinking-capable local models
from spending their bounded completion budget on an unreturned reasoning trace. LM
Studio receives only the common OpenAI-compatible request fields. Both local providers
receive the full answer contract through `response_format.type: json_schema`, not only
a generic JSON-mode hint; NemoFold still validates the returned object and every quote
independently. The schema narrows question IDs and collection sizes to the current job;
the validator still rejects duplicate question accounting or cross-question evidence.

The generic registry deliberately contains no Nebius adapter. Nebius/Nemotron remains
the separate `token-factory-preflight` / `token-factory-run` route with its immutable
package, current price inputs, exactly-once transfer attempt, and competition verifier.
A generic provider result always records `competition_proof: false` and
`cloud_proof: false`, even when a transfer and a schema-valid response occurred.

The Codex and Claude bridges are personal test conveniences, not authentication
proxies for a product. They run in a new temporary directory, disable writes and
session persistence, pass only the pseudonymized prompt, invoke an argv array without
a shell, and remove `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from the child environment.
The Codex bridge explicitly disables its shell, app, browser, computer-use, image,
hook, memory, plugin, and skill-search features in addition to requesting a read-only
sandbox. The Claude bridge supplies an empty tool list under safe mode.
For a multi-user product, use the official provider API adapters instead.

## Relation to the existing agent modules

NemoFold's provider layer is an application-specific evidence engine, not a new
general agent launcher. The existing modules remain separated by responsibility:

| Module | Existing responsibility | NemoFold decision |
|---|---|---|
| COMA | Provider-neutral process lifecycle, job board, status, and polling | Preferred future lifecycle backend for long-running agents, but not a current hard dependency |
| BACH `AgentLauncherHandler` | BACH persona discovery, interactive Claude windows, PID files, and operator notes | Host-specific compatibility surface; do not import it into NemoFold |
| clutch | Model discovery, cost/availability routing, and general provider execution | Optional future model-selection input; NemoFold keeps its evidence schema and transfer gates authoritative |
| ellmos-agent-bridge | Partner metadata and delegation recommendations | Metadata only; it does not replace execution or evidence validation |
| WorkflowHooker | Lifecycle hooks, closing gates, and rare emergency blockers | Useful around long unattended workflows, not inside a bounded provider request |
| CodeBox | Local IDE and process surfaces under the invoking user | Not an operating-system sandbox and therefore not a provider isolation boundary |

The current subscription bridge deliberately uses a smaller internal `ProcessRunner`
contract. A request is passed over stdin, runs in a fresh temporary directory with a
minimal environment, has a hard timeout, and uses the provider's structured-output
contract. COMA 0.2.1 is already the correct architectural owner for generic lifecycle,
but its current public `SpawnSpec` has no stdin payload, its adapters do not express all
of NemoFold's schema and feature-disable flags, and its Windows termination path does
not yet promise full child-process-tree cleanup. Importing it now would weaken the
tested boundary rather than consolidate it.

The intended convergence seam is therefore explicit: when COMA exposes bounded stdin,
process-tree supervision, and pass-through structured-output constraints, a COMA-backed
implementation can satisfy NemoFold's existing `ProcessRunner` protocol. The evidence
validator, privacy decision, budget gate, and separate Nebius competition path remain in
NemoFold. The BACH launcher should then consume COMA for spawning instead of becoming a
dependency of NemoFold.

## Runtime verification on 2026-08-31

The following synthetic-only checks were executed on `WORKSTATION-LG`; none of
them contained a private user document:

| Path | Runtime evidence | Result |
|---|---|---|
| Ollama | Real `qwen3:4b` call through `ollama_dynamic_schema_20260831` | Executed; ledger verification valid; no external transfer |
| Codex CLI | Real signed-in subscription call through `codex_subscription_safe_20260831` | Executed; ledger verification valid; external transfer recorded; no competition proof |
| Claude Code | Real signed-in subscription call through `claude_subscription_safe_20260831` | Executed; ledger verification valid; external transfer recorded; no competition proof |
| LM Studio | Real loopback socket transport against the documented `/v1/chat/completions` contract | Contract test passed; the LM Studio application/runtime was not installed on this host |
| OpenAI / Anthropic APIs | Request and response contracts exercised with deterministic transports | No live call: no API keys or cost authorization were present |
| Nebius Token Factory | Dedicated adapter, immutable-package, transfer, and proof tests | Kept separate; no new paid live call was made during this provider audit |

The three executed ledgers can be rechecked with `python -m nemofold verify <ledger>`.
Generic-provider execution never upgrades either `competition_proof` or `cloud_proof`.

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

The repository also contains a one-question, synthetic-only runtime smoke that can be
used without copying private documents:

```powershell
python -m nemofold analyze-provider --job examples\jobs\provider-local-smoke.json `
  --allow-root $PWD --run-id local_smoke --provider ollama --model qwen3:4b
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

For an intentionally external but synthetic-only bridge smoke, use
`examples\jobs\provider-external-smoke.json`. It contains no private documents and
still requires both external-transfer flags shown above.

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

This exposes eight typed tools:

- `nemofold_capabilities`
- `nemofold_anonymize`
- `nemofold_preview`
- `nemofold_run`
- `nemofold_analyze_with_provider`
- `nemofold_save_draft`
- `nemofold_list_drafts`
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
`run_id` is optional on the loopback preview, run, provider-preview, and provider-run
endpoints; the server assigns a fresh ID when it is omitted. A caller should provide one
only when it deliberately needs a stable external correlation key.

The loopback surface also exposes prepared-job and Research Notebook endpoints. A model
may save a strict job through `POST /api/drafts` for later browser review, or an Evidence
Analyst investigation through `POST /api/notebooks`. The browser can load these records
and explicitly trigger a run. `POST /api/notebook-run` links a run only when its ledger
exists inside that notebook's output scope; the server verifies the ledger and artifact
hashes before recording the link. These endpoints are absent from public-demo and
network-exposed surfaces. Neither record type stores API keys or approvals.

Example provider object:

```json
{
  "provider_id": "ollama",
  "model": "qwen3",
  "max_output_tokens": 32768,
  "timeout_seconds": 1800
}
```

The provider layer accepts up to 131072 output tokens and a 3600-second timeout. These
are response and request ceilings, not corpus-size limits. In the local console,
`max_chunks` bounds relevant evidence per question; it does not cap how many files are
inventoried and indexed.

## Upstream contracts

- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Anthropic Messages API](https://platform.claude.com/docs/en/api/http/messages/create)
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- [LM Studio REST API](https://lmstudio.ai/docs/developer/rest)
- [Codex CLI](https://learn.chatgpt.com/docs/codex/cli)
- [Claude Code headless mode](https://code.claude.com/docs/en/headless)
