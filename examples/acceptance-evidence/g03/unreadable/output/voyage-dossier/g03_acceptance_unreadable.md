# Voyage dossier · Dokumenteingang · Unlesbare Eingabe blockiert

Run g03_acceptance_unreadable · status stopped

The chain stopped at step 1. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · smart_inbox

- run: g03_acceptance_unreadable_01
- status: blocked
- artifacts: 3
- ledger: <evidence-root>\unreadable\output\smart_inbox\ledger\g03_acceptance_unreadable_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- errors: unreadable_input:01-scan-corrupt.txt
