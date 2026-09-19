# Voyage dossier · Policen-Inventar · fehlende Pflichtdaten

Run g04_acceptance_missing_data · status stopped

The chain stopped at step 1. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · document_registry

- run: g04_acceptance_missing_data_01
- status: blocked
- artifacts: 2
- ledger: <evidence-root>\missing-data-negative\out\registry\ledger\g04_acceptance_missing_data_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- errors: needs_user_input:columns.Police, needs_user_input:columns.Abdeckung
