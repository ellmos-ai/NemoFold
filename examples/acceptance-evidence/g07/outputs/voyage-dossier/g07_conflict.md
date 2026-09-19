# Voyage dossier · 

Run g07_conflict · status stopped

The chain stopped at step 2. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · document_registry

- run: g07_conflict_01
- status: executed
- artifacts: 4
- ledger: <evidence-root>\outputs\conflict_step1\ledger\g07_conflict_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 2 · medication_reconcile

- run: g07_conflict_02
- status: blocked
- artifacts: 2
- ledger: <evidence-root>\outputs\conflict_step2\ledger\g07_conflict_02.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- errors: conflicting_dosages:1
