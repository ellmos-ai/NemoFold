# Submission readiness

Last reconciled with the live Devpost form and judging page on 2026-08-30. This file is
an engineering gate, not a claim that registration or submission has occurred.

## Recommended track

**Personal AI.** NemoFold directly implements the requested private, persistent
assistant with durable memory, skills/workflows, tools, and controlled data access.
Its document-analysis depth also supports the broader apps-and-agents story, but the
submission should choose one primary track and keep the pitch focused.

## Judging criteria

| Criterion | Current evidence | Remaining acceptance gate |
|---|---|---|
| Technological implementation | One strict contract across web, CLI, and skill; eight workflows; persistent index; exact citations; reversible journal; privacy-package validator; fail-closed Token Factory adapter with result verifier; automated suite | Real Nebius runtime call using an NVIDIA open-source Nemotron model, with the generated sanitized request/response and usage evidence |
| Design | Coherent Captain Nemo console, explicit trust boundary, workflow defaults, safe preview path, accessible text alternative | Hosted working demo URL and a final interaction pass on the public build |
| Potential impact | Solves real folder-based knowledge and file-maintenance work; demonstrates coverage, conflicts, versioning, and undo | Short user acceptance session on a bounded real-world corpus and a recorded before/after result |
| Quality of idea | Separates persistent local authority from optional cloud reasoning; measures evidence rather than merely generating prose | Show the live hybrid loop end to end within the video |

## Mandatory deliverables

- Working project using Nebius Token Factory or Nebius AI Cloud and at least one NVIDIA
  open-source model: adapter ready and simulated locally; **real call OPEN and mandatory**.
- Public repository with OSI license visible near the top and setup/Nebius/NVIDIA use in
  the README: local repo ready; **public remote and final live-use documentation open**.
- Public working demo URL or test build: **OPEN**.
- Public YouTube or Vimeo demo, no longer than three minutes, with audio explaining
  Nebius and Nemotron use: script ready; **recording and upload open**.
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

The following require the user's explicit approval at the point of action:

1. accepting eligibility, rules, and Devpost terms and sending registration;
2. creating or publishing a remote repository;
3. creating accounts, spending credits, or calling Nebius/Nemotron;
4. hosting a demo or uploading the video;
5. sending the final Devpost submission.

No agreement checkbox may be set, and no experience score may be invented, merely to
make the readiness table green.
