# NemoFold

NemoFold is a private, evidence-first document agent. It turns explicitly approved
folders into a persistent working memory, keeps claims traceable to source locations,
and makes file actions reversible.

Working tagline: **Your files. Your rules. Your agent.**

This repository is the new competition implementation for the Nebius x NVIDIA Global
AI Hackathon. The local core is deliberately usable without a cloud account. NemoClaw,
OpenShell, Nemotron, and Nebius integration will be marked as proven only after a real,
sanitized runtime test exists.

## Current scope

- shared contracts for jobs, sources, evidence, gates, runs, artifacts, and undo
- fail-closed path, privacy, model, and cost policies
- idempotent run ledger and recovery state
- local evidence and coverage validation
- eight product workflows built on those shared cores

Implemented workflows: Smart Inbox; naming/format/retention policy; universal bundle;
continuous digest; evidence analyst; version resolver; five-format report studio; and
the shared platform proof.

The first executable milestone is a synthetic offline demo. Public repository creation,
cloud spend, uploads, and Devpost submission are separate human approval gates.

## Offline proof

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m nemofold demo --input examples\synthetic-home --output run-reports\demo
```

The report deliberately says `cloud_proof: false`. To exercise the fail-closed path:

```powershell
python -m nemofold demo --input examples\synthetic-home --output run-reports\blocked `
  --scenario blocked-external
```

The normal demo creates a text/manifest/ZIP bundle, folder digest, context receipts,
SQLite FTS index, Markdown/TXT/PDF/DOCX/ODT reports, and one run ledger. It moves and
undoes a synthetic inbox file to prove reversibility.

## Design and integration

- [Architecture](docs/architecture.md)
- [NemoClaw integration](docs/nemoclaw-integration.md)
- [Competition code map](COMPETITION_CODE_MAP.md)
- [Third-party software](THIRD_PARTY_LICENSES.md)
