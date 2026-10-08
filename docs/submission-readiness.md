# Submission readiness

## Technical assessment 2026-10-08

The implementation assessment below is pinned to
[`f43d669`](https://github.com/ellmos-ai/NemoFold/commit/f43d66975c241384d55afd11f25bcf929fef47c1).
It separates technical evidence from personal GUI and live submission acceptance.

| Deliverable | Current evidence and boundary |
|---|---|
| Working Nebius/NVIDIA implementation | A real paid Token Factory call to `nvidia/nemotron-3-super-120b-a12b` completed on 2026-09-02. Its committed receipt chain was re-verified offline on 2026-10-08: `valid=true`, `status=executed`, no errors. This is a historical cloud proof, not a new paid call. |
| Public source, license and setup | [MIT repository](https://github.com/ellmos-ai/NemoFold) with source, assets and [installation instructions](../README.md#7-installation--quick-start). |
| Complete technical regression | [Hosted CI for f43d669](https://github.com/ellmos-ai/NemoFold/actions/runs/37426667693): Windows/Python 3.12 passed 1155 tests; both Ubuntu/Python versions passed 1154 with one skip. The run completed 2026-10-06 and was read back 2026-10-08. |
| Fresh local package/system check | Source and wheel built on 2026-10-08; a separately installed wheel passed isolated import, CLI help, offline demo and verification of ten artifacts. Static checks and the 476-file evidence verification also passed. The resource-stopped local full-suite attempt is not claimed as passed. |
| Public demo or test-build access | [Free pinned source test build](https://github.com/ellmos-ai/NemoFold/archive/f43d66975c241384d55afd11f25bcf929fef47c1.zip), with setup and offline-demo commands below. No cloud account is required. A hosted public demo and a container runtime were not accepted in this check. |
| Public YouTube demo | [NemoFold demo](https://youtu.be/wOToLqDBvvE), the published v6 reference already recorded in the 2026-09-19 snapshot below. Today's technical check makes no new duration/audio or user media-acceptance claim. |
| Acceptance gates and user testing | G01–G16 are backed by committed synthetic evidence. G17/G18 are declared unsupported; the register reports `complete=false`. Personal GUI acceptance remains pending with the user. |
| Live Devpost content and answers | Final text, video embedding and custom answers require a separate current Devpost readback. The technical assessment alone does not establish that those fields were updated. |

### Account-free test build

Download the pinned source ZIP linked above, extract it, and open a terminal in
the extracted project folder. Use Python 3.11 or newer:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install ".[dev]"
.venv\Scripts\python -m nemofold --help
.venv\Scripts\python -m nemofold demo --input examples\synthetic-home --output run-reports\demo
.venv\Scripts\python -m nemofold verify run-reports\demo\ledger\demo_offline.json
.venv\Scripts\python -m nemofold verify-result examples\proven-run
```

On Linux/macOS substitute `.venv/bin/python`. The demo intentionally reports
`cloud_proof=false`; `verify-result` checks the separate historical cloud receipt.
The source archive was publicly reachable without authentication on 2026-10-08.
The [release gate](../RELEASE_GATE.md) records the complete technical scope.

G17's writing subscription adapter and G18's A3 FormBuilder/export adapter are
not implemented. Neither synthetic gate evidence nor CI replaces a personal
GUI test on an explicitly approved real folder. New live model calls, accounts,
hosting and agreement choices remain separate actions, with no invented survey
ratings or consent.

## Historical readiness snapshot 2026-09-19

The earlier assessment is preserved below. Its pending-hosted-CI, placeholder-video
and deployment wording belongs to that dated snapshot and is superseded by the
technical evidence above where explicitly stated.

<details>
<summary>Historical readiness snapshot, including the 2026-08-30 submission readback</summary>

Last reconciled with the live Devpost project and judging page on 2026-08-30; the
technical evidence below was re-measured on 2026-09-19. Project 1407423 is published
and submitted; this file distinguishes that submission fact from the still-open
hosted-demo, video-content, and user-acceptance evidence. The real Nebius Token
Factory call is no longer open — see the mandatory-deliverables list below.

## Recommended track

**Personal AI.** NemoFold directly implements the requested private, persistent
assistant with durable memory, skills/workflows, tools, and controlled data access.
Its document-analysis depth also supports the broader apps-and-agents story, but the
submission should choose one primary track and keep the pitch focused.

## Judging criteria

| Criterion | Current evidence | Remaining acceptance gate |
|---|---|---|
| Technological implementation | One strict contract across web, CLI, and skill; 44 registered workflows; persistent index; exact citations; reversible journal; privacy-package validator; fail-closed Token Factory adapter with no-network preflight and result verifier; portable `json_object` response mode plus a locally enforced schema; separate cloud/NemoClaw proof states; a real paid Nebius Token Factory call to `nvidia/nemotron-3-super-120b-a12b` completed 2026-09-02 (`cloud_proof: true`, committed and offline-reverifiable at `examples/proven-run/`); 16 of 18 internal acceptance gates `done` with committed re-hashable evidence (`nemofold acceptance-gates --evidence-root .`); 1082 local tests passing plus one Windows permission-skipped symlink test; the earlier eight-workflow commit had hosted CI green on Ubuntu/Python 3.11, Ubuntu/Python 3.12, and Windows/Python 3.12 | Hosted CI for the current commit (not yet re-run since the local gate/mypy fixes) |
| Design | Nautilus-themed product workspace with real top-level routes for Documents, Analysis, Routines, Artifacts, and Connections; area-specific workflows; visible authority ledger; exact evidence chain; grouped job contract; run dossier; responsive navigation and overflow controls; accessible text alternative/focus/contrast; and a capability-minimal synthetic-only hosting mode | Hosted working demo URL and a final interaction pass on the deployed build |
| Potential impact | Solves real folder-based knowledge and file-maintenance work; demonstrates coverage, conflicts, versioning, and undo | Short user acceptance session on a bounded real-world corpus and a recorded before/after result |
| Quality of idea | Separates persistent local authority from optional cloud reasoning; measures evidence rather than merely generating prose | Show the live hybrid loop end to end within the video |

## Mandatory deliverables

- Working project using Nebius Token Factory or Nebius AI Cloud and at least one NVIDIA
  open-source model: **DONE**. A real paid Token Factory call to
  `nvidia/nemotron-3-super-120b-a12b` completed 2026-09-02 with `status: executed` and
  `cloud_proof: true`; the complete receipt chain is committed at
  `examples/proven-run/` and re-verifiable offline without an account:
  `python -m nemofold verify-result examples/proven-run`.
- Public repository with OSI license visible near the top and setup/Nebius/NVIDIA use in
  the README: **DONE** at <https://github.com/ellmos-ai/NemoFold>; the earlier public
  eight-workflow commit has a green Linux/Windows
  [hosted CI run](https://github.com/ellmos-ai/NemoFold/actions/runs/33313331087).
  Hosted CI for the current commit (44 workflows, 16/18 acceptance gates `done`) stays
  open until the next authorized push; final live-use documentation remains open until
  the demo hosting and video steps below close.
- Public working demo URL or test build: capability-minimal synthetic hosting mode and
  a provider-neutral, non-root OCI/Docker definition are implemented locally; the image
  contract is statically tested, but no local Docker client was available for a container
  build and no host was changed; **deployment URL OPEN**.
- Public YouTube demo, no longer than three minutes, with audio explaining Nebius and
  Nemotron use: **DONE 2026-09-19** at <https://youtu.be/wOToLqDBvvE> (v6: the user-approved
  113-second v5 cut with the caption-free cinematic intro in front, 136.5 s in total,
  1920x1080, -18 LUFS; read back via YouTube oEmbed). No caption files by design, YouTube
  generates captions. The Devpost project still embeds the placeholder video from the
  precautionary submission; **replacing the Devpost video URL remains OPEN** (user action).
- Project description, technology list, track, model/prompting/comparison answers, and
  honest Nebius/Nemotron feedback: product story ready; the live run itself is done
  (see above), but drafting the experience-dependent answers from it and updating the
  Devpost submission with them remain **OPEN**.
- Existing-work disclosure: draft present in the product story; final answer must match
  the competition repository history.

## Devpost defaults from prior projects

Use the established profile answers without asking again: individual submitter,
working solo, Germany, organization `N/A`, Canada province `N/A`, and no Tavily unless
the implementation changes. Do not infer ratings, platform experience, legal consent,
or hackathon-specific survey answers.

## External-action gates

The following require the user's explicit approval at the point of action. Registration,
repository publication and the precautionary Devpost submission have already received
that approval and are complete; new actions still use the same boundary:

1. accepting eligibility, rules, and Devpost terms and sending registration;
2. creating or publishing a remote repository;
3. creating accounts, spending credits, or calling Nebius/Nemotron;
4. hosting a demo or uploading the video;
5. replacing or materially updating the live Devpost submission.

No agreement checkbox may be set, and no experience score may be invented, merely to
make the readiness table green.

</details>
