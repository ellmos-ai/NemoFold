# Submission readiness

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
| Technological implementation | One strict contract across web, CLI, and skill; 43 registered workflows; persistent index; exact citations; reversible journal; privacy-package validator; fail-closed Token Factory adapter with no-network preflight and result verifier; portable `json_object` response mode plus a locally enforced schema; separate cloud/NemoClaw proof states; a real paid Nebius Token Factory call to `nvidia/nemotron-3-super-120b-a12b` completed 2026-09-02 (`cloud_proof: true`, committed and offline-reverifiable at `examples/proven-run/`); 16 of 18 internal acceptance gates `done` with committed re-hashable evidence (`nemofold acceptance-gates --evidence-root .`); 1082 local tests passing plus one Windows permission-skipped symlink test; the earlier eight-workflow commit had hosted CI green on Ubuntu/Python 3.11, Ubuntu/Python 3.12, and Windows/Python 3.12 | Hosted CI for the current commit (not yet re-run since the local gate/mypy fixes) |
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
  Hosted CI for the current commit (43 workflows, 16/18 acceptance gates `done`) stays
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
