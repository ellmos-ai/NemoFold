# NemoFold

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
| Universal Bundle | Deterministic text bundle, manifest, ZIP, hashes, and explicit unsupported/unreadable entries |
| Continuous Folder Digest | Persistent inventory snapshots with new, changed, unchanged, and deleted source IDs |
| Evidence Analyst | Persistent SQLite FTS index, multiple questions, exact quotes, source catalog, line/page locations, coverage and reports |
| Version Resolver | Per-family resolution, explicit validity/date/version priority, named file-time fallback, and line comparison |
| Report & Artifact Studio | A validated analysis contract rendered to Markdown, TXT, PDF, DOCX, and ODT |
| NemoClaw Platform & Proof | Path-free, hashed job packages plus a fail-closed Nebius Token Factory adapter and independently verifiable result receipt; the real competition run remains open |

The shared cores are the runtime, policy/privacy gate, run ledger/recovery, evidence
engine, and artifact export. Local extraction supports text-family files, JSON, CSV,
HTML, PDF, DOCX, and ODT. Unsupported or unreadable files remain visible as coverage
gaps.

Cloud spend, uploads, live NemoClaw/Nebius execution, and Devpost submission are
separate human approval gates.

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

## Approved Nebius Token Factory run

The live adapter is a separate, irreversible transfer gate. It accepts only the
official Nebius Token Factory HTTPS origin, rejects redirects, checks a conservative
cost ceiling before the request, reads the key only from `NEBIUS_API_KEY`, and refuses
to repeat a package that already contains `result.json` or a durable transfer attempt.

```powershell
$env:NEBIUS_API_KEY = "<session-only-key>"
python -m nemofold token-factory-preflight <package-directory> `
  --input-price-usd-per-million <current-input-rate> `
  --output-price-usd-per-million <current-output-rate> `
  --max-completion-tokens 1200
python -m nemofold token-factory-run <package-directory> `
  --approve-live-transfer `
  --input-price-usd-per-million <current-input-rate> `
  --output-price-usd-per-million <current-output-rate> `
  --max-completion-tokens 1200 `
  --declared-nemoclaw-version <captured-installed-version>
python -m nemofold verify-result <package-directory>
Remove-Item Env:\NEBIUS_API_KEY
```

The two rates are mandatory inputs because pricing can change; copy them from the
current provider pricing at execution time. The sanitized `result.json` binds the
exact request, response, usage, rate inputs, cost, endpoint, model, timestamps, and
model output to the immutable local package. It contains no Authorization header or
API key. A failed provider response records `transfer_performed: true` but never
`cloud_proof: true`. If the connection ends without a response, the pre-request
`transfer-attempt.json` remains in place, reports an uncertain transfer state, and
blocks an unsafe automatic retry.

`token-factory-preflight` performs no network request and writes no transfer receipt.
It validates the immutable package, endpoint, explicit Nemotron model, JSON request,
current caller-supplied prices, conservative maximum cost, job budget, duplicate-run
guards, and whether a session key is present. Its output always keeps
`network_called`, `transfer_performed`, and `cloud_proof` false; a pass is readiness,
not execution evidence and not transfer approval.

The request uses Token Factory's documented `json_object` response mode. NemoFold
includes its complete output schema inside the bounded user payload and validates the
returned object locally. It therefore does not depend on model-specific server-side
JSON-schema enforcement to protect the evidence contract.

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
and requires `--expose-network` before it will bind to a non-loopback address. Preview
is the default safe path; action workflows additionally require the server-side
`--approve-actions` gate before an apply request can succeed.

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
- [NemoClaw integration](docs/nemoclaw-integration.md)
- [Product story](docs/product-story.md)
- [Three-minute jury demo](docs/jury-demo.md)
- [Jury design set and Nautilus brand kit](docs/media/designset/README.md)
- [Submission readiness](docs/submission-readiness.md)
- [Competition code map](COMPETITION_CODE_MAP.md)
- [Third-party software](THIRD_PARTY_LICENSES.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Release gate](RELEASE_GATE.md)
