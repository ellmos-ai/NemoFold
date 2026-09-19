# Voyage dossier · 

Run g08_pos · status executed

## Step 1 · document_registry

- run: g08_pos_01
- status: executed
- artifacts: 4
- ledger: <evidence-root>\outputs\pos_step1\ledger\g08_pos_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 2 · database_reader

- run: g08_pos_02
- status: executed
- artifacts: 3
- ledger: <evidence-root>\outputs\pos_step2\ledger\g08_pos_02.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 3 · folder_digest

- run: g08_pos_03
- status: executed
- artifacts: 2
- ledger: <evidence-root>\outputs\pos_step3\ledger\g08_pos_03.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- handoff: markdown from g08_pos_02 (SHA-256 51e203a253502103fd5c731057a87512ad2efec91510034c0855046d2be9d515)
