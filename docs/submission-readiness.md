# Submission readiness

Last reconciled with the live Devpost project and judging page on 2026-08-30. Project
1407423 is published and submitted; this file distinguishes that submission fact from
the still-open live runtime, hosted-demo, video-content, and user-acceptance evidence.

## Recommended track

**Personal AI.** NemoFold directly implements the requested private, persistent
assistant with durable memory, skills/workflows, tools, and controlled data access.
Its document-analysis depth also supports the broader apps-and-agents story, but the
submission should choose one primary track and keep the pitch focused.

## Judging criteria

| Criterion | Current evidence | Remaining acceptance gate |
|---|---|---|
| Technological implementation | One strict contract across web, CLI, and skill; twelve workflows; persistent index; exact citations; reversible journal; privacy-package validator; fail-closed Token Factory adapter with no-network preflight and result verifier; portable `json_object` response mode plus a locally enforced schema; separate cloud/NemoClaw proof states; 202 local tests passing plus one Windows permission-skipped symlink test; the earlier eight-workflow commit had hosted CI green on Ubuntu/Python 3.11, Ubuntu/Python 3.12, and Windows/Python 3.12 | Hosted CI for the current twelve-workflow commit and a real Nebius runtime call using an NVIDIA open-source Nemotron model, with the generated sanitized request/response and usage evidence |
| Design | Evidence-console direction with visible authority ledger, exact evidence chain, grouped job contract, run dossier, explicit trust boundary, responsive overflow controls, accessible text alternative/focus/contrast, and a capability-minimal synthetic-only hosting mode | Hosted working demo URL and a final interaction pass on the deployed build |
| Potential impact | Solves real folder-based knowledge and file-maintenance work; demonstrates coverage, conflicts, versioning, and undo | Short user acceptance session on a bounded real-world corpus and a recorded before/after result |
| Quality of idea | Separates persistent local authority from optional cloud reasoning; measures evidence rather than merely generating prose | Show the live hybrid loop end to end within the video |

## Mandatory deliverables

- Working project using Nebius Token Factory or Nebius AI Cloud and at least one NVIDIA
  open-source model: adapter ready and simulated locally; **real call OPEN and mandatory**.
- Public repository with OSI license visible near the top and setup/Nebius/NVIDIA use in
  the README: **DONE** at <https://github.com/ellmos-ai/NemoFold>; current Linux/Windows
  [hosted CI run](https://github.com/ellmos-ai/NemoFold/actions/runs/33313331087) passed.
  Final live-use documentation remains open until the real provider run.
- Public working demo URL or test build: capability-minimal synthetic hosting mode and
  a provider-neutral, non-root OCI/Docker definition are implemented locally; the image
  contract is statically tested, but no local Docker client was available for a container
  build and no host was changed; **deployment URL OPEN**.
- Public YouTube demo, no longer than three minutes, with audio explaining Nebius and
  Nemotron use: a URL is present on Devpost. The local 73.07-second Andrew v3 draft uses
  the redesigned product UI, contains no embedded subtitle stream, and has passed audio,
  layout, contrast, render, window-attribution and frame readback checks. A deterministic
  19-cue English VTT plus SRT fallback and a hashed upload packet are prepared locally,
  but the video is not yet user-approved or uploaded; **video-content acceptance OPEN**.
- Project description, technology list, track, model/prompting/comparison answers, and
  honest Nebius/Nemotron feedback: product story ready; experience-dependent answers
  remain **OPEN until the live run**.
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
