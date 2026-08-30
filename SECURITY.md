# Security policy

## Supported version

Security fixes currently target the latest commit on `main`. NemoFold is pre-1.0
software and does not yet promise maintenance for older snapshots.

## Reporting a vulnerability

Please use GitHub's private **Report a vulnerability** form in the repository Security
tab. Do not open a public issue for a suspected vulnerability or include real secrets,
private documents, host paths, or personal data in a report.

Useful reports identify the affected version, entry point, expected security invariant,
and a minimal synthetic reproduction. No real Nebius key or private corpus is needed.

## Product security boundaries

- Local paths are restricted to operator-provided allow roots.
- File actions require an explicit apply gate, a deterministic plan, and a reversible
  journal.
- External packages must pass the path, secret, schema, hash, and budget gates.
- The web console is loopback-only unless network exposure is explicitly enabled.
- The separate public demo mode reads only an operator-selected synthetic fixture,
  forces local-only dry-run authority, removes model/action capabilities, caps parallel
  work, uses per-request temporary output, and redacts host paths from responses.
- Live cloud execution remains unproven until a sanitized runtime receipt validates.
