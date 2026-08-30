# Public release gate

Gate date: 2026-08-30

## Local acceptance

- `python -m ruff check src tests`: pass
- `python -m mypy src`: pass for 30 source files
- `python -m pytest -q`: 132 passed
- `python -m compileall -q src tests`: pass
- `node --check src/nemofold/web/app.js`: pass
- `python -m build`: source and wheel distributions built
- `git diff --check`: pass
- Focused format check for changed source and tests: pass

The repository-wide format check is not asserted because 21 unchanged pre-existing
files are outside the current formatting slice.

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
- Sanitized NemoClaw runtime proof
- Public working demo and YouTube video
- Final Devpost submission

## Hosted repository acceptance

- Public repository: <https://github.com/lukisch/NemoFold>
- First hosted CI: [run 33293608035](https://github.com/lukisch/NemoFold/actions/runs/33293608035),
  pass on Ubuntu/Python 3.11, Ubuntu/Python 3.12, and Windows/Python 3.12
- Accepted revision: `f3f47d700c3daa39f6dd38f5365fe59dc9507c02`
