# Voyage dossier · 

Run g12_missing · status stopped

The chain stopped at step 3. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · document_registry

- run: g12_missing_01
- status: executed
- artifacts: 3
- ledger: <evidence-root>\work\missing_out1\ledger\g12_missing_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 2 · contact_monitor

- run: g12_missing_02
- status: executed
- artifacts: 4
- ledger: <evidence-root>\work\missing_out2\ledger\g12_missing_02.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 3 · controlled_email

- run: g12_missing_03
- status: handoff_blocked
- artifacts: 0
- ledger: <evidence-root>\work\missing_out3\ledger\g12_missing_03.json
- model: nemofold-local-core (level: default)
- model note: No model or consumer ran: the artifact handoff failed.
- outbound rights: draft_only (level: default)
- errors: recipient_not_found_in_contact_book:Dr. med. Nicht Vorhanden
