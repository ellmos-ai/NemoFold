# Voyage dossier · g13_negative_hash_mismatch

Run vy_g13_hash_mismatch · status stopped

The chain stopped at step 1. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · document_qa

- run: vy_g13_hash_mismatch_01
- status: blocked
- artifacts: 1
- ledger: <evidence-root>\runs\hash_s1\ledger\vy_g13_hash_mismatch_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- errors: source_document_hash_mismatch:actual=dde9bd40a83764833b69c8e173fbf5daf211e4b04c0c78101d8cda36d7e4ac99:expected=0000000000000000000000000000000000000000000000000000000000000000
