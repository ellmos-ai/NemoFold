# Voyage dossier · g13_negative_unbound_placeholders

Run vy_g13_unbound · status stopped

The chain stopped at step 1. Later steps were not started, so nothing downstream ran on an unfinished result.

## Step 1 · document_qa

- run: vy_g13_unbound_01
- status: blocked
- artifacts: 2
- ledger: <evidence-root>\runs\unbound_s1\ledger\vy_g13_unbound_01.json
- model: nemofold-local-core (level: default)
- model note: No preference was set at any level; the local engine is the default.
- outbound rights: draft_only (level: default)
- errors: unbound_fields_in_document:count=4:tokens={{klient_vorname}},{{klient_nachname}},[PLATZHALTER: Zielsetzung]
