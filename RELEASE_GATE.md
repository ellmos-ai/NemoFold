# Public release gate

## Gate 2026-09-19

- `python -m ruff check src tests`: pass.
- `python -m mypy src`: pass for 93 source files, and separately with
  `--platform linux` and `--platform darwin`: 0 errors each.
- `python -m pytest -q`: 1085 passed, 1 skipped (the same Windows privilege-dependent
  symlink test in `tests/e2e/test_webapp.py` as the 2026-09-01 gate below).
- `nemofold acceptance-gates --evidence-root .`: 16 of 18 registered Ellmos use-case
  acceptance gates (`G01`-`G18`) claim `done`, each re-verified against committed
  evidence (444 files, 1.8 MB, under `examples/acceptance-evidence/`; 476 files checked
  by the command). `G17` and `G18` remain `not_supported` with recorded boundary
  reasons. Without `--evidence-root` the command fails closed with exit code 2 by
  design (`done_gate_requires_evidence_root:G01`); this is asserted, not a defect.
- Every registered job contract runs end to end: all 43 names in `SUPPORTED_WORKFLOWS`
  reach either a completed or a blocked outcome with a stated reason, write nothing
  outside their output directory, and leave the read corpus unchanged.
- `git diff --check`: pass.
- `.github/workflows/ci.yml` gained two steps not present at the 2026-09-01 gate: the
  gate-register verification above, and `mypy src --platform linux && mypy src
  --platform darwin` alongside the existing host-platform `mypy src`.
- Fixed all 82 mypy errors that had kept hosted CI red since 2026-09-17 (five root
  causes, not 82 independent bugs: an invariant `list[object]` parameter, ten
  unguarded optional `Path` dereferences, twenty-six loop variables mypy bound to
  their first branch, four parameters that only needed `Sequence`, and a handful of
  individual dereference/formatting fixes); no `type: ignore` and no `Any` were added.
- Not independently re-measured at this gate (unchanged from 2026-09-01 unless noted
  above): `python -m compileall -q src tests`, `node --check src/nemofold/web/app.js`,
  `python -m build`, ruff format check, the Token Factory preflight, the synthetic HTTP
  demo runtime, the OCI/Docker contract tests, the evidence-console UI tests, the
  provider-neutral evidence core, the MCP stdio acceptance, and the Chrome readback.
- The first "External evidence still open" item below (real Nebius Token Factory run)
  was resolved the day after the 2026-09-01 gate: a real paid run completed
  2026-09-02, committed and offline-reverifiable at `examples/proven-run/`
  (`python -m nemofold verify-result examples/proven-run`). The remaining items in
  that list (live provider acceptance, NemoClaw runtime proof, public deployment,
  video upload, final Devpost readback) were not re-checked at this gate.

## Gate 2026-09-01

## Local acceptance

- `python -m ruff check src tests`: pass
- `python -m mypy src`: pass for 64 source files, and separately with
  `--platform linux` and `--platform darwin`. Type checking only the host platform
  hides every Windows-only attribute behind a guard the checker cannot narrow, which
  is how a green local run met a red Linux job.
- `python -m pytest -q`: 741 passed, one Windows privilege-dependent symlink test
  skipped. Rerun with openpyxl hidden from the import system, standing in for a runner
  that never installed it: 737 passed, five skipped, no failure.
- Every registered job contract runs end to end: all 34 names in `SUPPORTED_WORKFLOWS`
  reach either a completed or a blocked outcome with a stated reason, write nothing
  outside their output directory, and leave the read corpus unchanged.
- `python -m compileall -q src tests`: pass
- `node --check src/nemofold/web/app.js`: pass
- `python -m build`: source and wheel distributions built
- `git diff --check`: pass
- Ruff format check for the Python files changed in this slice: pass
- Local Token Factory preflight over the immutable synthetic package: pass with
  `network_called=false`, `transfer_performed=false`, and `cloud_proof=false`; API key,
  current provider prices, explicit user approval, model-catalog readback, and the real
  request remain external gates.
- Public synthetic HTTP demo runtime: executed with server-controlled roots,
  ephemeral output, no external model authority, no file-action authority, and
  `cloud_proof=false`.
- Provider-neutral OCI/Docker definition: statically contract-tested for the bounded
  `serve-demo` entrypoint, synthetic-only copy scope, non-root runtime and health check;
  the container was not built locally because Docker is not installed on this workstation.
- Evidence-console UI: focused HTTP/UI tests pass; every job-contract ID is present and
  unique; the seven-stage evidence chain has explicit wrapping and responsive breakpoints.
- Provider-neutral evidence analysis: Ollama, LM Studio, Codex CLI, Claude Code, OpenAI,
  and Anthropic share one path/transfer/pseudonymization/schema/quote-validation core
  behind CLI, loopback HTTP, and MCP. The network-exposed HTTP mode and public demo both
  disable the provider route.
- Official MCP SDK stdio acceptance: a real client initialization, tool listing, and
  `nemofold_anonymize` call pass. The installed server was read back as enabled in Codex
  and connected in Claude Code, with filesystem authority limited to this repository.
- No live or paid provider request was made. Ollama is installed but no Ollama or LM
  Studio listener was running during acceptance; provider transports were tested with
  deterministic fake HTTP and process boundaries.
- Local Chrome readback at 1920x1080 and 1440x1200 confirms the authority ledger, job
  console and all seven evidence-chain labels remain bounded.
- Claude Fable 5 completion review found no blocking issue. Its actionable authority,
  response-contract, contrast, focus, ARIA and breakpoint findings were applied and
  locally re-tested. A separate autonomous provider/MCP review was attempted with full
  repository read/write authority on 2026-08-31, but Claude stopped with HTTP 429 at the
  monthly spend limit before producing a review result; no source file was changed by
  that incomplete attempt, and no Fable pass is claimed for this provider slice.

The repository-wide format check is not asserted: 76 unchanged pre-existing files are
outside the current formatting slice, and reformatting them would bury this slice's
changes in unrelated churn.

`python -m build` produces a distribution carrying a direct git reference, which PyPI
refuses to accept. NemoFold is installable from source and from git; publishing to the
index would first require the optional templates dependency to be released there.

## Privacy and security acceptance

- Tracked files and Git history were checked for credential shapes, private absolute
  paths, risky generated formats, and personal-data markers with a synthetic positive
  control.
- Matches were limited to explicitly synthetic test fixtures and documented API-key
  placeholders; no credential or private source document was identified.
- The sequential high-risk security review covered path policy, file actions and undo,
  local HTTP handling, strict job parsing, external package validation, Token Factory
  transport, result verification, pseudonymization, inventories, extraction, artifacts,
  and ledgers.
- Stored action-plan tampering and provider-reflected secret persistence were fixed and
  regression-tested before publication.
- The provider-response regression set includes valid JSON values, JSON keys, allowed
  response headers, and invalid-JSON bodies.
- An independent security worker was unavailable in this runtime; this was a sequential
  review, not an independent multi-reviewer audit.

## External evidence still open

- Real Nebius Token Factory plus NVIDIA Nemotron run
- Live acceptance against Ollama, LM Studio, Codex, Claude, OpenAI, or Anthropic; the
  adapters and protocol boundaries are tested without making a provider request
- Sanitized NemoClaw runtime proof
- Public deployment of the implemented synthetic-only demo mode
- User acceptance and upload of the checked local 73.07-second Andrew v3 video draft;
  deterministic English VTT/SRT sidecars and the upload packet are ready, but the linked
  Devpost YouTube video has not been replaced
- Final live-content readback of the already submitted Devpost project

## Hosted repository acceptance

- Public repository: <https://github.com/ellmos-ai/NemoFold>
- Current hosted CI: [run 33313331087](https://github.com/ellmos-ai/NemoFold/actions/runs/33313331087),
  pass on Ubuntu/Python 3.11, Ubuntu/Python 3.12, and Windows/Python 3.12
- That hosted run covers the current public baseline, not the still-local provider/MCP
  slice. A fresh hosted result must be read back after an explicitly approved push.
- Public baseline before the local synthetic-demo slice:
  `c1d086a53a44f0e4403a6ad5621a32f43c1877c4`
- Secret Scanning and Push Protection were re-enabled after the organization transfer;
  Dependabot Security Updates and private vulnerability reporting remain enabled.
