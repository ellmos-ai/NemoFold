# Voyage dossier · 

Run g12_ambig · status stopped

The chain stopped at step 3. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · document_registry

- run: g12_ambig_01
- status: executed
- artifacts: 3
- ledger: <evidence-root>\work\ambig_out1\ledger\g12_ambig_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 2 · contact_monitor

- run: g12_ambig_02
- status: executed
- artifacts: 4
- ledger: <evidence-root>\work\ambig_out2\ledger\g12_ambig_02.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 3 · controlled_email

- run: g12_ambig_03
- status: handoff_blocked
- artifacts: 0
- ledger: <evidence-root>\work\ambig_out3\ledger\g12_ambig_03.json
- model: nemofold-local-core (level: default)
- model note: No model or consumer ran: the artifact handoff failed.
- outbound rights: draft_only (level: default)
- errors: ambiguous_recipient_in_contact_book:Dr. Weber:matches=['Dr. med. Claudia Weber', 'Dr. med. Frank Weber']
