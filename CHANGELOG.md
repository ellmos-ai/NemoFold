# Changelog

All notable changes to NemoFold are documented here.

## 0.2.0 - 2026-09-18

- Discoverability and visual architecture overhaul (Pfad B standard):
  - 18-point Quick Navigation anchor index across README.md and README_de.md with
    100% mutual anchor parity and `<a id="..."></a>` aliases for seamless cross-lingual browsing.
  - Shields.io badge suite covering Version 0.2.0, CI, 740+ passing tests (100% green),
    Python 3.11+, multi-OS (Windows, Linux, macOS), Privacy (100% Local-First & Zero-Egress),
    Security (RunAsInvoker unprivileged user mode), Security SLA (48h/5d triage),
    Third-Party Licenses (Audited & Permissive), Marketing Log, ellmos-ai ecosystem,
    open-bricks umbrella, and LLM-Ready context.
  - Four structured target developer and practitioner personas ([PERSONA-01] to [PERSONA-04])
    covering Legal & Due Diligence Analysts, Enterprise Privacy Officers, Autonomous Agent Developers,
    and Investigative Journalists & Evidence Curators.
  - High-intent bilingual SEO search terms for developer and enterprise discoverability.
  - 10-dimension comparative matrix vs. 4 industry alternatives (Cloud AI Assistants,
    Desktop Search Tools, Agent Orchestration Frameworks, Ad-hoc Python Extraction Scripts)
    mapped directly to ten governance and runtime invariants (INV-LOCAL-01 to INV-SLA-10).
  - Dual Mermaid diagrams: System Architecture Topology (`flowchart TB`) across five
    semantic layers and Evidence-Grounded Workflow Lifecycle (`sequenceDiagram` with `autonumber`).
  - Sibling tools and umbrella ecosystem cross-reference table covering 16 partner repositories.
  - German statutory liability exclusion notice (§ 521 BGB Gefälligkeitsrecht) in `README_de.md`.
  - Comprehensive Third-Party License Audit (`THIRD_PARTY_LICENSES.md`) certifying zero copyleft
    runtime dependencies, permissive licensing, unprivileged execution, and runtime invariant compliance.
  - Local marketing and discoverability register (`MARKETING-LOG.txt`).
  - Extended PEP 621 metadata URLs and classifiers in `pyproject.toml`.
  - Machine-readable context update in `llms.txt`.
  - Automated metadata contract verification suite in `tests/unit/test_metadata.py`.
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
- Make multi-source registry-to-synopsis handoffs explicitly traceable across
  producer and consumer Source ID namespaces, with matching source hashes;
  reject the Voyage result if the consumer snapshot or live hashes differ.
- Bind text, HTML, DOCX, ODT, and PDF extraction to the same in-memory bytes
  checked against each inventoried source hash; fail if a source changes while
  it is being read rather than citing unverified content.
- Bind SQLite-main-file, XLSX, and opt-in structured CSV rendering to one
  inventoried byte snapshot. Fail a workflow with active SQLite sidecars rather
  than silently omit an unbound database from its claims.
- Carry source-keyed structured-reader omission and missing-table notes into
  persisted RunReports, including read-bearing previews and registry-to-synopsis
  step ledgers and Voyage dossiers. Pass declared structured-source choices to
  every job-bearing reader callsite; the full Ellmos application gates remain open.
- Preserve declared SQLite table selection and opt-in CSV reading across a selected
  document-registry-to-synopsis handoff; stop the consumer before execution if its
  settings widen or change the producer's source scope. Validate these settings in
  the strict job contract, and extract cited registry fields from labelled table rows.
  Bind topic-matching structured row line numbers across producer and consumer, so
  unrelated rows in the same selected file do not enter the synopsis. Warn in reader
  notes and RunReports when long cell values or headers must be truncated. This remains
  a partial G02 use-case path, not full application acceptance.
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
