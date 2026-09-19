# Voyage dossier · 

Run g08_insufficient · status stopped

The chain stopped at step 1. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · database_reader

- run: g08_insufficient_01
- status: blocked
- artifacts: 2
- ledger: <evidence-root>\outputs\insufficient_step1\ledger\g08_insufficient_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- errors: insufficient_database_records:0<1
