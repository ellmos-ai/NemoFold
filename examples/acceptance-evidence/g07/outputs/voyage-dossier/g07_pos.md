# Voyage dossier · 

Run g07_pos · status executed

## Step 1 · document_registry

- run: g07_pos_01
- status: executed
- artifacts: 4
- ledger: <evidence-root>\outputs\pos_step1\ledger\g07_pos_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 2 · medication_reconcile

- run: g07_pos_02
- status: executed
- artifacts: 3
- ledger: <evidence-root>\outputs\pos_step2\ledger\g07_pos_02.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 3 · folder_digest

- run: g07_pos_03
- status: executed
- artifacts: 2
- ledger: <evidence-root>\outputs\pos_step3\ledger\g07_pos_03.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- handoff: markdown from g07_pos_02 (SHA-256 e33d241eafbdec5d1845707b5bb7ac958e4441e04190a641bcd06e2eae7eed81)
