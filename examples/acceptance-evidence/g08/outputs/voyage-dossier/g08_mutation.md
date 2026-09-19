# Voyage dossier · 

Run g08_mutation · status stopped

The chain stopped at step 1. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · database_reader

- run: g08_mutation_01
- status: blocked
- artifacts: 1
- ledger: <evidence-root>\outputs\mutation_step1\ledger\g08_mutation_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- errors: database_modification_blocked:non_select_statement:DROP
