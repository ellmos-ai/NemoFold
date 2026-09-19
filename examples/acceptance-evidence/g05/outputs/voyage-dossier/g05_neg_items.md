# Voyage dossier · g05_insufficient_items_voyage

Run g05_neg_items · status stopped

The chain stopped at step 2. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · document_registry

- run: g05_neg_items_01
- status: executed
- artifacts: 4
- ledger: <evidence-root>\outputs\neg_items_01_registry\ledger\g05_neg_items_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 2 · cost_timeline

- run: g05_neg_items_02
- status: blocked
- artifacts: 2
- ledger: <evidence-root>\outputs\neg_items_02_timeline\ledger\g05_neg_items_02.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- errors: insufficient_cost_items:1<5
