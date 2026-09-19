# Voyage dossier · 

Run g11_low_qual · status stopped

The chain stopped at step 1. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · ocr_pipeline

- run: g11_low_qual_01
- status: blocked
- artifacts: 2
- ledger: <evidence-root>\work\low_qual_step1\ledger\g11_low_qual_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- errors: low_ocr_quality_review_required:1_documents, scan-degraded.pdf:page_1_conf_0.40_synthetic_ocr_extraction_low_quality
