# Voyage dossier · Schilddrüse · Diagnoseanfrage blockiert

Run g02_acceptance_medical_authority · status stopped

The chain stopped at step 2. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · document_registry

- run: g02_acceptance_medical_authority_01
- status: executed
- artifacts: 4
- ledger: <evidence-root>\medical-authority-negative\out\register\ledger\g02_acceptance_medical_authority_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)

## Step 2 · synopsis_merge

- run: g02_acceptance_medical_authority_02
- status: blocked
- artifacts: 2
- ledger: <evidence-root>\medical-authority-negative\out\synopsis\ledger\g02_acceptance_medical_authority_02.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- errors: medical_authority_denied:diagnosis
- handoff: document-registry from g02_acceptance_medical_authority_01 (SHA-256 ae20e89a6dd463593f2d1b8904b1b903b004a54b6f95578c8fd4099aac7bc3c2)
