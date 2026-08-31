# NemoFold

English | [Deutsch](README_de.md)

[![CI](https://github.com/ellmos-ai/NemoFold/actions/workflows/ci.yml/badge.svg)](https://github.com/ellmos-ai/NemoFold/actions/workflows/ci.yml)
[MIT License](LICENSE) · Python 3.11+ · Local-first

NemoFold is a private, evidence-first document agent. It turns explicitly approved
folders into a persistent working memory, keeps claims traceable to source locations,
and makes file actions reversible.

Working tagline: **Your files. Your rules. Your agent.**

This repository is the new competition implementation for the Nebius x NVIDIA Global
AI Hackathon. The local core is deliberately usable without a cloud account. NemoClaw,
OpenShell, Nemotron, and Nebius integration will be marked as proven only after a real,
sanitized runtime test exists.

## What is implemented

| Workflow | Local result |
|---|---|
| Smart Inbox | Extension-based routing plan, all-or-nothing collision gate, journaled moves, resume and undo |
| Naming, Format & Retention | Rule resolution, naming/retention checks, dry-run, reversible move/copy, and TXT/MD/RST conversion copies |
| Cleanup Rules | Manual bulk routing plus readable suggestions learned only from explicit corrections; suggestions never activate themselves |
| Mail-to-Case | Read-only local EML intake, source-grounded case dossier, manifest, and hash-recorded attachment extraction |
| Controlled Email | Local RFC 822 draft and exact approval digest; send requests fail closed without immediate confirmation and a proven server adapter |
| Universal Bundle | Deterministic text bundle, manifest, ZIP, hashes, and explicit unsupported/unreadable entries |
| Continuous Folder Digest | Persistent inventory snapshots with new, changed, unchanged, and deleted source IDs |
| Evidence Analyst | Persistent SQLite FTS index, multiple questions, exact quotes, source catalog, line/page locations, coverage and reports |
| Version Resolver | Per-family resolution, explicit validity/date/version priority, named file-time fallback, and line comparison |
| Contact Monitor | Source-quoted contact and responsibility candidates, named snapshot comparison, and no automatic deletion |
| Report & Artifact Studio | A validated analysis contract rendered to Markdown, TXT, PDF, DOCX, and ODT |
| NemoClaw Platform & Proof | Path-free, hashed job packages plus a fail-closed Nebius Token Factory adapter and independently verifiable result receipt; the real competition run remains open |

The Analysis Lab also includes the local **Research Notebook** workspace. It keeps an
investigation goal, approved roots, reusable questions/prompts, provider configuration,
and a trail of verified run ledgers together without storing API keys or approvals.

The shared cores are the runtime, policy/privacy gate, run ledger/recovery, evidence
engine, provider adapter core, MCP surface, and artifact export. Local extraction
supports text-family files, JSON, CSV, HTML, PDF, DOCX, and ODT. Unsupported or
unreadable files remain visible as coverage gaps.

Cloud spend, uploads, live NemoClaw/Nebius execution, and further Devpost changes
remain separate human approval gates.

![NemoFold Captain Nemo console](docs/media/nemofold-console.png)

## Install

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m nemofold --help
```

Every non-demo command consumes the same strict `nemofold.job.v1` JSON contract. See
[`schemas/nemofold-job-v1.schema.json`](schemas/nemofold-job-v1.schema.json) and the
[`examples/jobs`](examples/jobs) directory.

## Offline proof

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m nemofold demo --input examples\synthetic-home --output run-reports\demo
```

The report deliberately says `cloud_proof: false`. To exercise the fail-closed path:

```powershell
python -m nemofold demo --input examples\synthetic-home --output run-reports\blocked `
  --scenario blocked-external
```

The normal demo creates a text/manifest/ZIP bundle, folder digest, context receipts,
SQLite FTS index, Markdown/TXT/PDF/DOCX/ODT reports, and one run ledger. It moves and
undoes a synthetic inbox file to prove reversibility.

## Run a real local job

```powershell
$runId = "local_analysis_1"
python -m nemofold preview --job examples\jobs\evidence-local.json `
  --allow-root $PWD --run-id $runId
python -m nemofold run --job examples\jobs\evidence-local.json `
  --allow-root $PWD --run-id $runId
python -m nemofold verify run-reports\evidence-local\ledger\$runId.json
```

`preview` does not run an external model or apply file actions. For an external-model
job it writes the exact pseudonymized context package that would be eligible to leave
the host and records `transfer_performed: false`. A later `run` still blocks unless a
real external runtime adapter and the explicit privacy/model/cost gates are present.

`nemofold package` turns an `allow_once` job into a hashed, path-free local NemoClaw
directory and validates it immediately. It still performs no upload and records
`transfer_performed: false`; see [NemoClaw integration](docs/nemoclaw-integration.md).

## Use any supported model through one evidence core

NemoFold can send only its locally selected and pseudonymized evidence context to
Ollama, LM Studio, a personal Codex/Claude Code CLI, or the official OpenAI/Anthropic
APIs. Returned claims are accepted only when every quote is present in the outbound
context for that question. Provider selection is runtime configuration; it does not
change the strict job contract.

```powershell
python -m nemofold providers
python -m nemofold analyze-provider --job examples\jobs\evidence-local.json `
  --allow-root $PWD --run-id ollama_1 --provider ollama --model qwen3
```

The same service is available at `POST /api/provider-analyze` and through the stdio
MCP server:

```powershell
codex mcp add nemofold -- python -m nemofold mcp --base-dir $PWD --allow-root $PWD
claude mcp add --scope user nemofold -- python -m nemofold mcp `
  --base-dir $PWD --allow-root $PWD
```

Local providers are restricted to loopback. External adapters require `allow_once`, a
server-side external-model gate, and per-call transfer approval. Keys come only from
environment variables. Generic provider receipts never become Nebius competition
proof; the next section remains the only such route. See
[Provider adapters, local API, and MCP](docs/providers-and-mcp.md).

## Approved Nebius Token Factory run

### Model choice and what Token Factory contributes

The configured model is NVIDIA Nemotron 3 Super
(`nvidia/nemotron-3-super-120b-a12b`), served by
[Nebius Token Factory](https://nebius.com/services/token-factory/nemotron). It was
chosen deliberately for this product: the weights are fully open under the NVIDIA
Open License (the hackathon requires an NVIDIA open-source model); its
agentic-reasoning and instruction-following profile matches NemoFold's strict
JSON-bound evidence contract; the long context window carries a whole bounded
evidence package in one request; and the hybrid MoE design (about 12B active of
120B parameters) keeps the conservative per-call cost ceiling far below the job
budget. The adapter enforces the `nvidia/nemotron-` prefix twice, in preflight and
again before transport.

Token Factory contributes the one step the product cannot do locally: a strong
hosted reasoning pass over the prepared evidence bundle. Everything else - the
originals, paths, index, policies, journal, and verification - stays on the local
machine; only pseudonymized bounded chunks cross the gate, and the sanitized result
is bound back into the locally verified receipt chain. A real paid run remains an
explicit user gate and has not been claimed anywhere in this repository.

The live adapter is a separate, irreversible transfer gate. It accepts only the
official Nebius Token Factory HTTPS origin, rejects redirects, checks a conservative
cost ceiling before the request, reads the key only from `NEBIUS_API_KEY`, and refuses
to repeat a package that already contains `result.json` or a durable transfer attempt.
After the cost gate and before it writes any receipt, it confirms the exact model ID
against the live `/v1/models` catalog. That call is an authorized metadata read; it
carries no job content, so a retired or mistyped model ID aborts without a receipt and
leaves the package fully runnable. A confirmed catalog records
`model_catalog_checked: true` in the result, and the verifier rejects a result that
claims otherwise.

```powershell
$env:NEBIUS_API_KEY = "<session-only-key>"
python -m nemofold token-factory-preflight <package-directory> `
  --input-price-usd-per-million <current-input-rate> `
  --output-price-usd-per-million <current-output-rate> `
  --max-completion-tokens 8192
python -m nemofold token-factory-run <package-directory> `
  --approve-live-transfer `
  --input-price-usd-per-million <current-input-rate> `
  --output-price-usd-per-million <current-output-rate> `
  --max-completion-tokens 8192 `
  --declared-nemoclaw-version <captured-installed-version>
python -m nemofold verify-result <package-directory>
Remove-Item Env:\NEBIUS_API_KEY
```

The two rates are mandatory inputs because pricing can change; copy them from the
current provider pricing at execution time. Reasoning models spend completion
tokens on thinking before the JSON answer, so keep `--max-completion-tokens`
generous; the conservative cost gate still checks the resulting ceiling against the
job budget before any request. The sanitized `result.json` binds the exact request,
the sanitized response (`response_sha256` is computed over the sanitized body, never
over raw provider bytes), usage, rate inputs, cost, endpoint, model, timestamps, and
model output to the immutable local package. It contains no Authorization header or
API key. A failed provider response records `transfer_performed: true` but never
`cloud_proof: true`. If the connection ends without a response, the pre-request
`transfer-attempt.json` remains in place, reports an uncertain transfer state, and
blocks an unsafe automatic retry. Recovery after any burned attempt is deliberate,
not destructive: build a fresh immutable package with `nemofold package` under a new
`run_id` and run that. Existing receipts are never deleted, so the failed attempt
stays auditable while the new package remains runnable.

`token-factory-preflight` performs no network request and writes no transfer receipt.
It validates the immutable package, endpoint, explicit Nemotron model, JSON request,
current caller-supplied prices, conservative maximum cost, job budget, duplicate-run
guards, and whether a session key is present. Its output always keeps
`network_called`, `transfer_performed`, and `cloud_proof` false; a pass is readiness,
not execution evidence and not transfer approval. It therefore reports
`model_catalog_checked: false`: the catalog is confirmed by `token-factory-run`, which
is the only command allowed to touch the network.

The request uses Token Factory's documented `json_object` response mode and carries
only documented chat-completion parameters, because one undocumented field that the
endpoint rejects would spend the single approved run on an HTTP 400. NemoFold includes
its complete output schema inside the bounded user payload and validates the returned
object locally. It therefore does not depend on model-specific server-side JSON-schema
enforcement to protect the evidence contract.

The optional declared NemoClaw version is metadata only. The result records
`nemoclaw_proof: false`; only a separately captured, sanitized runtime log from the
actual sandbox may support a NemoClaw execution claim.
The earlier pre-release option `--nemoclaw-version` was intentionally removed because
its name implied proof; scripts must use `--declared-nemoclaw-version` instead.

Action jobs additionally require `--approve-actions`. A completed action run can be
reversed with `nemofold undo <run-id> --output <dir> --allow-root <root>
--approve-actions`. Failed or blocked jobs can be retried with `nemofold resume` while
preserving the original job identity and journal.

## Open the local web console

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m nemofold serve --allow-root $PWD --base-dir $PWD
```

Open `http://127.0.0.1:8765`. The console uses the same strict job parser and
application service as the CLI. It starts on loopback only, rejects cross-origin POSTs,
and requires `--expose-network` before it will bind to a non-loopback address. Even
then the authority-bearing surfaces stay loopback-only: a network-exposed server
refuses job preview and execution, exactly like drafts, artifacts, and providers;
hosting for other people goes through `serve-demo`. Preview is the default safe path;
action workflows additionally require the server-side `--approve-actions` gate before
an apply request can succeed.

The overview and six work areas use distinct, bookmarkable routes instead of in-page
scroll jumps: `/document-center`, `/analysis`, `/routines`, `/artifacts`,
`/connections`, and `/governance`. The overview itself stays deliberately bare — one
headline, one sentence and the six area cards — and folds the boundary tiles, the
evidence chain, the contract register and the roadmap behind an antique ship's chart
that unfolds on click or Enter. Nothing is removed; documentation simply stops
crowding the surface. Each area opens with what lives there rather than with the job
form: Document Center counts the approved corpus, Folder Routines reads the
last routine ledgers, and every area offers task cards that prepare the contract below.
The Command Bridge at `/governance` renders the authority this server was started with —
the file-action, external-model and network gates, approved roots, budget ceiling and
contracted workflows — and holds Storage Policies. Gates are read there, never granted
there: a closed gate still requires a restart with the matching flag. Analysis Lab
combines deterministic bundle preparation, privacy preflight, Evidence Analyst, reusable
prompt sets, and persistent
Research Notebooks. Artifact Studio opens executed or blocked ledgers and verifies every
recorded artifact hash. Connections is a pure status page that keeps configured
adapters, executed provider runs, transfers, and cloud proof visibly separate. Document Center also contains explainable Cleanup Rules,
read-only Mail-to-Case intake, and Controlled Email drafts; Folder Routines includes the
source-grounded Contact Monitor. A model can prepare the same settings for browser review
through `draft-save`, MCP, or the loopback draft API; approvals are always reset.

Controlled Email does not claim network delivery in the default runtime. It writes the
exact draft and approval digest, then blocks a send request until the same digest is
confirmed and a separately proven server-side mail adapter exists. Mail-to-Case accepts
approved local `.eml` files; it does not silently connect to a mailbox.

### Run the capability-minimal synthetic demo

Use the separate demo command when the console may be reachable by people who must not
receive local file authority:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m nemofold serve-demo --demo-root examples\synthetic-home
```

`serve-demo` accepts only five read-only workflows over the committed synthetic corpus.
Input and output roots, workflow parameters, privacy mode, action mode, model access and
budget are server-controlled. Every request receives an isolated temporary output area
that is removed after the sanitized response is returned. The command exposes neither
file-action nor external-model flags and still binds to loopback unless both a non-local
host and `--expose-network` are supplied. It is a capability-minimal hosting surface,
not proof of a Nebius, Nemotron or NemoClaw runtime call; `cloud_proof` remains false.

## Trust boundary

- Original files, absolute paths, persistent index, policies, ledger, validation, and
  actions stay local.
- Only selected chunks, questions, artificial source IDs, schema and a bounded budget
  can enter an external package.
- The package validator rejects host paths, secrets, undeclared files, changed hashes,
  symlinks, or residual sensitive patterns—even if a manifest was re-hashed.
- `cloud_proof: true` is invalid without a successful, schema-valid provider response
  bound to runtime evidence. The repository contains the adapter and simulated tests,
  but deliberately contains no claim that the pending real competition call succeeded.

## Design and integration

- [Evidence-console interface direction](docs/design-direction.md)
- [Architecture](docs/architecture.md)
- [Provider adapters, local API, and MCP](docs/providers-and-mcp.md)
- [Capability-minimal demo deployment](docs/deployment.md)
- [NemoClaw integration](docs/nemoclaw-integration.md)
- [Product story](docs/product-story.md)
- [Document Services roadmap](docs/document-services-roadmap.md)
- [Three-minute jury demo](docs/jury-demo.md)
- [Jury design set and Nautilus brand kit](docs/media/designset/README.md)
- [Submission readiness](docs/submission-readiness.md)
- [Competition code map](COMPETITION_CODE_MAP.md)
- [Third-party software](THIRD_PARTY_LICENSES.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Release gate](RELEASE_GATE.md)
