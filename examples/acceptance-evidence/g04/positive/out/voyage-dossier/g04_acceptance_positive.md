# Voyage dossier · Versicherungen erfassen, normalisieren und analysieren

Run g04_acceptance_positive · status executed

## Step 1 · document_registry

- run: g04_acceptance_positive_01
- status: executed
- artifacts: 4
- ledger: <evidence-root>\positive\out\registry\ledger\g04_acceptance_positive_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 2 · coverage_timeline

- run: g04_acceptance_positive_02
- status: executed
- artifacts: 4
- ledger: <evidence-root>\positive\out\timeline\ledger\g04_acceptance_positive_02.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 3 · folder_digest

- run: g04_acceptance_positive_03
- status: executed
- artifacts: 2
- ledger: <evidence-root>\positive\out\digest\ledger\g04_acceptance_positive_03.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- handoff: markdown from g04_acceptance_positive_02 (SHA-256 543488fbe9dcac474ea1822d478ab46d96ca1995fc3f0825b0088e5f29587548)
