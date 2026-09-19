# Voyage dossier · g06_insufficient_subs_voyage

Run g06_neg_subs · status stopped

The chain stopped at step 2. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · document_registry

- run: g06_neg_subs_01
- status: executed
- artifacts: 4
- ledger: <evidence-root>\outputs\neg_subs_01_registry\ledger\g06_neg_subs_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 2 · subscription_reconcile

- run: g06_neg_subs_02
- status: blocked
- artifacts: 2
- ledger: <evidence-root>\outputs\neg_subs_02_reconcile\ledger\g06_neg_subs_02.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- errors: insufficient_subscriptions:1<5
