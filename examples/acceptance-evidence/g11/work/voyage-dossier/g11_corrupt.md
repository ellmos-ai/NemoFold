# Voyage dossier · 

Run g11_corrupt · status stopped

The chain stopped at step 1. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · ocr_pipeline

- run: g11_corrupt_01
- status: blocked
- artifacts: 1
- ledger: <evidence-root>\work\corrupted_step1\ledger\g11_corrupt_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- errors: ocr_pipeline_execution_error:corrupted_or_unreadable_pdf:corrupted.pdf:invalid or encrypted PDF document: corrupted.pdf
