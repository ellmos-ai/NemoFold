# NemoFold interface direction

- Status: accepted for local MVP
- Date: 2026-08-31
- Supersedes: generic hero, rounded panel and equal feature-card direction

## Decision

The product UI uses an **Instrument / Evidence Console** as its primary direction and an **Editorial Evidence Dossier** for results. A restrained deep-sea identity appears only in the masthead, trust boundary and NemoFold color system. Controls remain sober and operational.

This direction replaces the generic AI landing-page pattern of a giant slogan, glassy rounded panels and equal feature cards. NemoFold should look like a document instrument whose assertions can be audited, not like an open-ended chat surface.

## Product and media split

- **Product:** compact evidence workspace, visible authority state, exact scope, square controls, ledgers and registers.
- **Demo media:** Captain Nemo, Nautilus, living deep-sea document creatures and the more expressive neon palette may carry the story.
- **Shared recognition:** the NemoFold wordmark, cyan local-state signal, orange policy gate and dark ocean ink.

## Evidence model

The interface exposes one stable chain:

`ORIGIN -> PATH -> INDEX -> POLICY -> CLAIM -> AUDIT -> ACTION`

Each stage has one job. Long labels must wrap inside their own cell; no label may cross a boundary. Remote reasoning appears only after the policy gate. Reports return to local validation before an action can be authorized.

## Component grammar

- **Routed product areas:** Overview, Document Center, Analysis Lab, Folder Routines,
  Artifact Studio, and Connections use distinct URLs and full page navigation. The
  interface does not jump between distant anchors on one long dashboard.
- **Case file:** states the current question and product truth without a marketing hero.
- **Boundary ledger:** distinguishes local readiness, action mode and live cloud proof.
- **Scope rail:** explains the strict job contract and execution sequence.
- **Job console:** groups mission, territory, and authority rather than presenting one undifferentiated form.
- **Run dossier:** adds compact status facts above the full machine-readable JSON evidence.
- **Trust boundary:** visually separates the local zone, policy gate and isolated worker.
- **Product map:** groups twelve technical contracts into Document Center, Analysis Lab,
  Folder Routines, Artifact Studio, and Connections.
- **Research Notebook:** keeps a local investigation goal, source scope, question set,
  provider route, and verified ledger trail together without persisting approval.
- **Artifact Studio:** makes success, rejection, evidence ledgers, outputs, and hash
  verification directly inspectable.
- **Connection ledger:** separates configured adapters, verified provider execution,
  transfer receipts, and cloud or competition proof.

### Navigation model

- `/` is the short orientation and product map, not an execution form.
- `/folders` is the home of the folders: which are watched, what is on board, and the
  use cases bound to them.
- `/processes` holds three tabs: Workflows (all use cases, filtered by topic tag),
  Registry (every job contract on its own) and Artifacts (the output catalogue).
- `/governance` holds the gates this server was started with, plus the Policies and
  Rules registers and the exceptions to them.
- The former `/document-center`, `/analysis`, `/routines` and `/artifacts` routes
  redirect to their replacement; a link naming one contract lands in the registry.
- `/artifacts` opens the verified artifact catalog directly.
- `/connections` is status-only and never upgrades configuration into runtime proof.

Each work page exposes only its relevant workflow choices. Navigation uses ordinary
links so browser back/forward, refresh, copying a URL and opening a section in a new
tab all behave predictably.

### Provider worker contract

The provider selector is part of the job contract, not a generic model playground.
It therefore follows mission, territory, and authority. Local and external workers
share one compact control grammar, while external transfer adds a separate native
checkbox and requires `privacy_mode=allow_once`.

- **Local core:** deterministic NemoFold workflow, no model transfer.
- **Loopback worker:** Ollama or LM Studio; `local_only` remains required.
- **External worker:** Codex, Claude, OpenAI, or Anthropic receives only selected,
  pseudonymized chunks after both server and one-run gates are open.
- **Proof boundary:** provider execution and transfer receipts never promote a
  generic result to Nebius competition proof or cloud proof.
- **Runtime truth:** listing a provider contract is not presented as a successful
  health check; readiness is established by a real bounded run.

## Density and responsive behavior

Desktop uses a 270-pixel authority rail and a flexible console. Evidence-chain cells use `minmax(0, 1fr)` and `overflow-wrap: anywhere` so long translated or runtime-provided strings stay bounded. The chain becomes four and then two columns on narrower screens. Forms become one column below 680 pixels. Primary navigation becomes a horizontally scrollable route strip on narrow screens rather than disappearing.

## Accuracy and accessibility

- Cloud proof remains visibly false until a verified live response exists.
- Public demo mode is labelled synthetic and read-only by runtime status.
- A text alternative describes the trust-boundary diagram.
- Status changes use text as well as color.
- Keyboard focus is visible on every interactive element.
- Small signal text and focus outlines meet a 4.5:1 contrast target on the paper surface.
- Reduced-motion preferences are honored; the product UI has no essential animation.

## Demo acceptance views

1. The case file and evidence chain establish the product in one frame.
2. The job console shows approved roots, a question and dry-run authority.
3. Preview produces a dossier without implying a cloud call.
4. The trust boundary explains what Nemotron can and cannot receive.
5. The product map reveals that NemoFold does more than one analysis workflow.
6. The local console distinguishes local-core, loopback-provider, blocked external,
   approved external, running, rejected, and validated-result states.
7. The Analysis Lab can save and reopen a multi-run Research Notebook, while Artifact
   Studio independently verifies the linked ledgers and outputs.
8. Each primary navigation item opens a distinct route without an in-page scroll jump,
   and browser back/forward preserves understandable navigation history.

## Provider acceptance gate

- A new user can identify source scope, privacy mode, selected worker, transfer
  state, and the next authorized action without opening chat.
- External runs require both `allow_once` and an explicit one-run checkbox.
- Local provider runs require `local_only` and show no external-transfer warning.
- The public synthetic demo cannot call the provider route.
- Provider results expose provider identity, transfer state, report state, and proof
  limitations.
- Long provider labels, model names, paths, and errors remain inside their cells at
  1440×900 and 390×844; 1280×720 and 1920×1080 remain capture targets.

## Rejected directions

- **Chat-first assistant:** hides source structure and suggests ambient authority.
- **Generic AI landing page:** communicates category conventions instead of NemoFold's evidence model.
- **Full submarine dashboard:** expressive, but too decorative for frequent document work.
- **Editorial report everywhere:** excellent for final claims, too passive for configuring and previewing jobs.
