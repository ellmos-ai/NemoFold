# Voyage dossier · Versicherungsverlauf · fehlende Deckungsdaten

Run g04_acceptance_missing_dates · status stopped

The chain stopped at step 1. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · coverage_timeline

- run: g04_acceptance_missing_dates_01
- status: blocked
- artifacts: 2
- ledger: <evidence-root>\missing-dates-negative\out\timeline\ledger\g04_acceptance_missing_dates_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- errors: insufficient_coverage_intervals:0<1
