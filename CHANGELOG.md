# Changelog

All notable changes to NemoFold are documented here.

## [Unreleased]

- Code review fixes and Chunk Export (2026-10-06):
  - New workflow `chunk_export` (roadmap DS06): cuts every readable approved source into
    deterministic, overlapping retrieval chunks for an external RAG index. Each chunk
    carries its source id, relative source name, character offsets, lines, a token
    estimate and the SHA-256 of its exact text; a manifest records the settings, every
    source with its status (`chunked`, `empty`, `not_read`) and the hash of the chunk
    file. A corpus that needs more chunks than `max_chunks` blocks the run whole instead
    of being exported in part. Wired into the CLI/API/MCP job contract, the Captain's
    Desk, the workflow graph gallery and the console registry.
  - Security: the local console now rejects GET requests with a non-local Host header
    (DNS rebinding could read approved roots, ledgers and artifact contents before).
    Malformed Host/Origin headers and deeply nested JSON bodies are refused with 403/400
    instead of crashing the handler; the public demo refuses non-string `workflow` and
    `model_id` values.
  - Privacy: the pseudonymous Relation Model report no longer quotes the sentence that
    names the people; it cites the line instead, like the pseudonymous JSON. The Token
    Factory API key is kept out of `repr`.
  - Rollback: a failed undo can be retried; previously the second attempt collided with
    its own failed ledger entry and the files could never be restored.
  - Ingestion: DOCX/ODT extraction skips tracked deletions, field codes and change logs,
    and keeps line breaks and tabs; malformed XML parts count as unreadable sources
    instead of aborting the run; HTML extraction drops `script`, `style` and `template`.
  - Time: dates are read in written order, impossible dates and hours are dropped, a
    clock time is no longer lent to a neighbouring date, and closeness checks use real
    calendar arithmetic (no more 31-day months at the end of February).
  - Primitives: normalized deduplication keeps numbers with their sign and separators
    apart (`-500` vs `500`, `5,000` vs `5.000`); a dash only separates a label when
    spaced, so `Name-Zusatz:` is no longer read as `Name`; anchor totals survive the
    second aggregation stage; symbol-only statements are kept instead of vanishing.
  - Job files: BOM-prefixed UTF-8 loads; non-UTF-8 files, overflowing, NaN or infinite
    budgets and malformed `pattern_mining` bounds are reported as job file errors at
    preview instead of tracebacks; an undecodable ledger no longer blocks artifact views.
  - Console listings: `truncated` is only reported when the cap actually cut entries.
  - CI: `auto-assign.yml` and `welcome.yml` group concurrency per pull request/issue, so
    two newcomers no longer cancel each other's run; organization repositories assign
    the PR author instead of the (unassignable) organization.
  - Tests: 1154 passed, 1 skipped (57 new regression, chunk-export and contract tests).

- Pfad B Discoverability, Level 1 SBOM Re-Audit & Marketing Registry (2026-10-03):
  - Level 1 SBOM Stand 2026-10-03: Re-audited `THIRD_PARTY_LICENSES.txt` and `THIRD_PARTY_LICENSES.md` certifying 100% permissive runtime dependencies (zero copyleft, zero AGPL/GPL), unprivileged `RunAsInvoker` non-elevation certification (INV-RUNAS-08), Zero-Egress isolation (INV-LOCAL-01), and formal compliance with `INV-LOCAL-01` through `INV-SLA-10`.
  - Bilingual Documentation & Badge Synchronization: Synchronized `README.md` and `README_de.md` badges to Verified-2026--10--03, Last-Checked-2026--10--03, and 1097 passed | 1 skipped tests; maintained 18-point dual reciprocal HTML anchor parity (`<a id="sec-01"></a>`..`<a id="sec-18"></a>`) and § 521 BGB German statutory notice.
  - Context Hygiene & RAG Index: Synchronized `llms.txt` (Last-checked: 2026-10-03, 1097 passed tests).
  - Local Marketing Register: Expanded `MARKETING-LOG.txt` with Section 9 detailing the 2026-10-03 Pfad B discoverability audit, 20/20 topic saturation verification, and non-automated recommendations for High-DPI Open Graph preview cards, terminal screencasts, and MCP directory submissions.
  - Version Freeze Discipline: Preserved version `0.2.1` strictly unchanged per `T-20260920-167562623`.
  - Contract Test Suite: Added automated contract test `test_pfad_b_discoverability_audit_currency_20261003` in `tests/unit/test_metadata.py` validating Level 1 SBOM currency, badge dates, and marketing log presence (22/22 passed | 100% green).

- Pfad A Technical Hygiene, Bilingual CONTRIBUTING Guidelines, Lock Defense & Level 1 SBOM Re-Audit (2026-10-01):
  - Bilingual Developer Guidelines: Replaced minimal stub with comprehensive bilingual `CONTRIBUTING.md` (EN/DE) specifying all 10 governance invariants `INV-LOCAL-01` through `INV-SLA-10`, unprivileged user-mode execution (`RunAsInvoker`), Plan D local development workflow (`C:\_Local_DEV\repos\NemoFold`), 48h Security Response SLA, and MIT licensing terms.
  - Multi-Host Cloud-Sync & Lock Defense: Hardened `.gitignore` with additional canonical lock patterns (`LOCK.dev.*`, `LOCK.antigravity.*`, `LOCK.bugsearch.*`), task plans (`TASKPLAN_*.md`), and host tokens (`*-IDEAPAD-GEI*`, `*-IDEAPAD-GEI.*`).
  - Level 1 SBOM Stand 2026-10-01 Re-Audit: Re-audited `THIRD_PARTY_LICENSES.txt` and `THIRD_PARTY_LICENSES.md` certifying 100% permissive dependencies (zero copyleft, zero AGPL/GPL), `RunAsInvoker` non-elevation, Zero-Egress isolation, and full compliance with `INV-LOCAL-01` to `INV-SLA-10`.
  - Documentation & Badge Parity: Synchronized `README.md` and `README_de.md` badges to Verified-2026--10--01, Last-Checked-2026--10--01, and 1096 passed | 1 skipped tests; updated `llms.txt` Stand 2026-10-01 with primary documentation reference to `CONTRIBUTING.md`.
  - Version Freeze Discipline: Preserved version `0.2.1` strictly unchanged per `T-20260920-167562623`.
  - Contract Test Suite Expansion: Expanded `tests/unit/test_metadata.py` with 3 new contract tests validating bilingual `CONTRIBUTING.md` invariant parity, extended `.gitignore` lock patterns, and Level 1 SBOM currency 2026-10-01 (21/21 passed | 100% green).

- Pfad A Technical Hygiene, CI Lifecycle Workflows & Level 1 SBOM Hardening (2026-09-28):
  - CI Lifecycle Automation: Provisioned `.github/workflows/auto-assign.yml` (actions/github-script@v7, timeout-minutes: 5, least-privilege `pull-requests: write`, concurrency cancellation) and `.github/workflows/label-sync.yml` (EndBug/label-sync@v2, timeout-minutes: 5, least-privilege `issues: write`).
  - Label Governance: Established canonical `.github/labels.yml` with 11 standard labels according to GOVERNANCE.md §4.2.
  - Multi-Host & Cloud-Sync Defense: Hardened `.gitignore` with host tokens (`*-IDEAPAD*`, `*_WORKSTATION*`, `*_WORKSTATION-LG*`, `*-WORKSTATION.*`, `*-WORKSTATION-LG.*`), canonical locks (`LOCK*.txt`, `.automation-lock`), and OS/editor artifacts (`Desktop.ini`, `Thumbs.db`, `ehthumbs.db`, `*.swo`, `*.swp`) while preserving `!package-lock.json` and `!uv.lock`.
  - PEP 621 Standardisation: Added `THIRD_PARTY_LICENSES.txt` to `license-files` in `pyproject.toml`, registered `"Third-Party Licenses (Text)"` in `[project.urls]`, and hardened `[tool.pytest.ini_options]` `norecursedirs` with `.pytest_tmp*` and `.tox`.
  - Level 1 SBOM Text Companion: Created `THIRD_PARTY_LICENSES.txt` companion file certifying zero copyleft dependencies, unprivileged user-mode execution (INV-RUNAS-08 `RunAsInvoker`), Zero-Egress isolation, and full compliance with INV-LOCAL-01 through INV-SLA-10.
  - Attribution & Notices: Updated root `NOTICE` with explicit cross-reference to `THIRD_PARTY_LICENSES.txt`; re-audited `THIRD_PARTY_LICENSES.md` as of 2026-09-28.
  - Context & Verification Badges: Synchronized `README.md`, `README_de.md`, and `llms.txt` with verified date `2026-09-28` and Level 1 SBOM Plain Text badge.
  - Version Freeze Discipline: Preserved version `0.2.1` strictly unchanged per `T-20260920-167562623`.
  - Contract Tests: Expanded `tests/unit/test_metadata.py` with automated contract verification for all new lifecycle workflows, labels, plain-text SBOM companion, gitignore multi-host tokens, and PEP 621 declarations.

- Pfad B Discoverability, Visual Architecture & Level 1 SBOM Audit (2026-09-26):
  - Canonical Root Attribution: Created `NOTICE` in the repository root formalizing copyright ownership for Lukas Geiger, `ellmos-ai`, and the `open-bricks` umbrella under MIT License.
  - Saturated GitHub Topics (20/20): Saturated remote repository topics on GitHub via `gh repo edit` and synchronized 20 keywords in `pyproject.toml` (`ai-agents`, `developer-tools`, `document-analysis`, `ellmos-ai`, `evidence-first`, `hackathon`, `local-first`, `mcp`, `mcp-server`, `nebius`, `nemotron`, `nvidia`, `offline-first`, `open-bricks`, `personal-ai`, `persistent-memory`, `privacy`, `python`, `reversible-actions`, `zero-egress`).
  - Canonical Homepage URL: Established `https://github.com/ellmos-ai/NemoFold#readme` on GitHub remote and in `pyproject.toml`.
  - Reciprocal Dual HTML Anchors: Integrated `<a id="sec-01"></a>` through `<a id="sec-18"></a>` across all 18 numbered sections in both `README.md` and `README_de.md` for seamless bilateral deep-linking and contract validation.
  - Level 1 SBOM Audit: Re-audited `THIRD_PARTY_LICENSES.md` Stand 2026-09-26 certifying zero copyleft runtime dependencies (100% permissive MIT, BSD-3-Clause, PSFL-2.0), unprivileged `RunAsInvoker` non-elevation certification (INV-RUNAS-08), Level 1 SBOM compliance, and formal cross-reference to `NOTICE`.
  - Statutory Legal Disclaimers: Added § 521 BGB German statutory notice (Gefälligkeitsrecht) and 48-hour Security Response SLA in Section 18 of `README.md` and `README_de.md`.
  - Local Marketing Register: Created canonical `MARKETING-LOG.txt` documenting repository audit baseline, 4 target personas, high-intent search queries, 10-dimension 5-way comparative matrix vs. alternatives, and governance invariants.
  - Manifest & Packaging Hardening: Added `license-files = ["LICENSE", "NOTICE", "THIRD_PARTY_LICENSES.md"]` and expanded `[project.urls]` (Notice, Marketing Log) in `pyproject.toml`.
  - Pytest Hardening: Added `--basetemp=.pytest_temp` and `.pytest_temp` / `.hypothesis` to `norecursedirs` in `pyproject.toml`; added `.pytest_temp/` to `.gitignore`.
  - Context Index: Updated `llms.txt` (Last-checked: 2026-09-26, test baseline, NOTICE entrypoint, § 521 BGB disclaimer, Level 1 SBOM notes).
  - Shields.io Badges: Synchronized badges across `README.md` and `README_de.md` (Attribution-NOTICE, Verified-2026--09--26, Last-Checked-2026--09--26, Tests 1085 passed | 1 skipped, Level 1 SBOM).
  - Version Freeze Discipline: Strictly enforced policy `T-20260920-167562623` preserving version `0.2.1` unchanged.

## 0.2.1 - 2026-09-19

- Pfad A Technical Hygiene & Lifecycle Hardening:
  - CI workflow lifecycle hardening: added concurrency controls (`cancel-in-progress: true`) and 15-minute job timeout to `.github/workflows/ci.yml`.
  - Added canonical automated lifecycle workflows `.github/workflows/stale.yml` (actions/stale@v9, 10 min timeout, least-privilege) and `.github/workflows/welcome.yml` (actions/first-interaction@v3, 5 min timeout).
  - Multi-host synchronization & canonical lock defense: hardened `.gitignore` with multi-host cloud-sync conflict patterns (`*conflicted copy*`, `*-WORKSTATION*`, `*-LAPTOP*`, `*-ASUS*`), canonical lock patterns (`LOCK`, `LOCK.*`), and local cache protections while explicitly preserving `uv.lock`.
  - Tooling & packaging hardening: configured `[tool.pytest.ini_options]` with `minversion = "7.0"`, `addopts = "-ra -v"`, and comprehensive `norecursedirs`.
  - Expanded `[tool.ruff.lint].select` with pycodestyle warnings (`"W"`).
  - Extended contract verification suite in `tests/unit/test_metadata.py` validating CI timeouts, concurrency, lifecycle workflows, gitignore defense, and pytest options.
  - Synchronized version 0.2.1 across `pyproject.toml`, `src/nemofold/__init__.py`, `llms.txt`, `THIRD_PARTY_LICENSES.md`, `README.md`, and `README_de.md`.

- Acceptance gates G01 through G16 now claim `done` in the shipped register, backed by
  committed evidence under `examples/acceptance-evidence/`. Each gate carries the pytest
  nodes that exercise it and one run receipt whose input and output manifests, verified
  handoffs, executed run report, passed result checks and blocked negative run are
  re-hashed from the committed files by `nemofold acceptance-gates --evidence-root .`.
  G17 and G18 remain `not_supported`.
- New `nemofold acceptance-evidence --work-dir <dir>` regenerates that evidence: it runs
  every gate bundle, exports the files its receipt references and rewrites the register.
  A gate whose bundle stops producing a verifiable receipt loses `done` instead of
  keeping a stale claim.
- Bundle reports carry the absolute path of the directory they ran in, which cannot be
  committed. The export replaces that prefix with an `<evidence-root>` token and leaves
  run ids, statuses, claims and check results untouched.
- `load_gate_register()` now refuses the shipped register without `--evidence-root`,
  because a `done` claim is unreadable without the files behind it. Bundles and tests
  start from the new `load_gate_register_template()` instead.
- Fixed all 82 mypy errors that had kept hosted CI red since 2026-09-17, plus the ruff
  findings in the metadata contract tests. CI now also type-checks for Linux and macOS
  and verifies the gate register against the committed evidence.
- Corrected README.md, README_de.md, RELEASE_GATE.md, COMPETITION_CODE_MAP.md and
  llms.txt to the measured state: `SUPPORTED_WORKFLOWS` registers 43 workflows, not the
  34 (or, in older passages, 16) the docs previously claimed; the test suite runs 1082
  passed / 1 skipped, not "740+ passed"; the Python/platform badges now name only what
  CI actually runs (3.11, 3.12 on Ubuntu and Windows; macOS is type-checked, not run).
  Documented the 16-of-18 acceptance gate register, its `nemofold acceptance-gates
  --evidence-root .` command and fail-closed exit code, and the
  `nemofold acceptance-evidence --work-dir <dir>` regeneration command in the README
  (new subsections in Section 6 and Section 8, both languages). Added the thirteen
  previously untabled workflows (`cost_timeline`, `subscription_reconcile`,
  `medication_reconcile`, `database_reader`, `knowledge_composer`, `routine_query`,
  `ocr_pipeline`, `document_qa`, `dossier`, `briefing`, `web_research`,
  `bundle_completeness_check`, `print_action`) to the README workflow tables.
  Corrected `docs/submission-readiness.md`, which had not been touched since
  2026-08-30: the real Nebius Token Factory run (2026-09-02, `examples/proven-run/`)
  was still listed as "OPEN and mandatory" there.

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
  - Local marketing and discoverability register (`MARKETING-LOG.txt`, since untracked as an internal working document).
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
