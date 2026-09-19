# Voyage dossier · 

Run g12_pos · status executed

## Step 1 · document_registry

- run: g12_pos_01
- status: executed
- artifacts: 3
- ledger: <evidence-root>\work\pos_out_step1\ledger\g12_pos_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 2 · contact_monitor

- run: g12_pos_02
- status: executed
- artifacts: 4
- ledger: <evidence-root>\work\pos_out_step2\ledger\g12_pos_02.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 3 · controlled_email

- run: g12_pos_03
- status: executed
- artifacts: 4
- ledger: <evidence-root>\work\pos_out_step3\ledger\g12_pos_03.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- handoff: contact-book from g12_pos_02 (SHA-256 94bafd4f146bbef04c0e56bffc1753663b8ac36919af3d75dde061a575998a60)
