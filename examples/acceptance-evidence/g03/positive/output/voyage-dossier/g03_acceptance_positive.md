# Voyage dossier · Dokumenteingang · Automatische Klassifikation und Index-Aktualisierung

Run g03_acceptance_positive · status executed

## Step 1 · smart_inbox

- run: g03_acceptance_positive_01
- status: executed
- artifacts: 3
- ledger: <evidence-root>\positive\output\smart_inbox\ledger\g03_acceptance_positive_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 2 · folder_digest

- run: g03_acceptance_positive_02
- status: executed
- artifacts: 2
- ledger: <evidence-root>\positive\output\digest\ledger\g03_acceptance_positive_02.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- handoff: action-plan from g03_acceptance_positive_01 (SHA-256 5201331f486c08a345fa25f04eb994977040ccdb6d68725bc4905844bff4598c)
