# Voyage dossier · g06_positive_subscription_reconcile_voyage

Run g06_pos · status executed

## Step 1 · document_registry

- run: g06_pos_01
- status: executed
- artifacts: 4
- ledger: <evidence-root>\outputs\positive_01_registry\ledger\g06_pos_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 2 · subscription_reconcile

- run: g06_pos_02
- status: executed
- artifacts: 3
- ledger: <evidence-root>\outputs\positive_02_reconcile\ledger\g06_pos_02.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 3 · folder_digest

- run: g06_pos_03
- status: executed
- artifacts: 2
- ledger: <evidence-root>\outputs\positive_03_digest\ledger\g06_pos_03.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- handoff: markdown from g06_pos_02 (SHA-256 bc5f0d97ab4f32c62f1348fcaddeec3bbc6e736024e2b8194dd241d9399c8159)
