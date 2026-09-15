# Changelog

All notable changes to NemoFold are documented here.

## Unreleased

- Execute saved voyages through the CLI and MCP as well as loopback HTTP, using
  the same chain runner and a shared response that includes verified handoff
  receipts. A one-run model override is validated identically on all surfaces;
  deterministic steps never claim to have called the requested model.
- Revalidate saved voyage steps on load so post-save changes to a typed edge,
  job, or allowed path cannot bypass the library contract.
- Bind each newly saved voyage to a SHA-256 receipt. Missing legacy receipts
  permit reading and resaving but block execution; altered top-level rights or
  model authority fail the receipt check. Pending-capability reservations cannot
  run even when their current steps happen to be implemented.
- Bind Voyage artifact edges to one written producer artifact with an in-root
  path and current SHA-256, and resolve topic-filtered document-registry rows
  to unchanged originals for synopsis merge. The full Ellmos application
  gates are still open.

- Expand the shared job contract from eight to twelve workflows with explainable
  Cleanup Rules, local Mail-to-Case intake, confirmation-bound Controlled Email
  drafts, and a source-grounded Contact Monitor.
- Keep cleanup suggestions inactive until declared as explicit rules, preserve each
  mail-case run, block unproven email delivery, and never auto-delete missing contacts.
- Add one provider-neutral analysis core shared by CLI, loopback HTTP API, and MCP,
  with Ollama, LM Studio, Codex CLI, Claude Code, OpenAI, and Anthropic adapters.
- Keep generic provider execution receipts explicitly separate from the dedicated
  Nebius/Nemotron competition-proof path.
- Reject non-finite job budgets and server cost limits across every model gate.
- Add a provider-neutral, non-root OCI/Docker package for the capability-minimal
  synthetic demo, with a bounded deployment contract and health-check evidence gate.

- Public repository and hosted CI acceptance.
- Revalidation of stored file-action plans before apply.
- Redaction of secret-like provider response values before durable logging.
- Capability-minimal synthetic public-demo server with server-owned roots, ephemeral
  outputs, bounded concurrency, no model/action authority, and host-path redaction.
- Evidence-console product UI with a visible authority ledger, bounded evidence chain,
  structured run dossier, responsive overflow rules, and accessible focus/contrast states.
- Synchronized German README with language navigation and identical command examples.
- Deterministic YouTube caption/export packet for the local Andrew v4 review render,
  showing the routed Analysis workspace while preserving the no-burn-in and no-upload
  approval boundary.

- Grow the shared job contract to thirty-four workflows, adding the case chronicle,
  structured and gated-web sources, delivery and completeness checks, and the checking
  and composing set: reference check, rater race, guide compose, wiki export, pattern
  mining, and template-filled documents and mail merges.
- Quote the line that answers each checklist item and never judge the document; report
  percent agreement and Cohen's kappa side by side, and say when kappa is undefined.
- Fill .docx templates through report-forge as an optional `templates` extra rather than
  reimplementing it, and name the install command instead of failing on an import.
- Repeat the message a workflow raised in the run report, so a failed run says which
  parameter is missing instead of only `workflow_error:ValueError`.
- Run every registered contract end to end in the test suite, so a declared workflow
  without an executor fails a gate rather than a user.

## 0.1.0 - 2026-08-30

- Eight local-first document and folder workflows behind one strict job contract.
- Persistent document index, exact evidence locators, coverage, and report exports.
- Reversible file-action journal with preview, resume, and undo.
- Path-free NemoClaw job package and fail-closed Nebius Token Factory adapter.
- Local web console, CLI, reusable skill, cross-platform CI, and jury design set.
