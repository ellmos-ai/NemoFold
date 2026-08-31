# NemoFold product story

## Tagline

Your files. Your rules. Your agent.

## Short pitch

NemoFold is a private, persistent document agent for people whose real work lives in
folders. It builds a durable local memory from explicitly approved sources, answers
questions with exact citations and coverage gaps, and performs only policy-checked,
reversible file actions. A privacy gate can release a bounded, pseudonymized context
package to a Nemotron worker while originals, paths, authority, validation, and the
audit trail remain local.

## The problem

Personal AI assistants often force an unsafe choice: keep sensitive documents local
and lose strong model reasoning, or upload broad folders and lose control and
traceability. They also treat every chat as temporary, return claims without precise
evidence, and cannot safely maintain the file system where the work actually lives.

## The product

NemoFold separates durable authority from optional reasoning. Its shared cores serve
twelve practical workflow chains:

1. Smart Inbox routes new files after a full-batch collision and policy preflight.
2. Storage Policies name, retain, move, copy, or convert files with dry-run and undo.
3. Cleanup Rules turns explicit corrections into readable suggestions while activating
   only separately declared, reversible bulk rules.
4. Mail-to-Case reads approved local EML files into a source-grounded case dossier.
5. Controlled Email creates an inspectable local draft and exact approval digest while
   blocking actual delivery without confirmation and a proven server adapter.
6. Bundle Export creates deterministic document packages with manifests and hashes.
7. Folder Digest records what is new, changed, stable, or deleted across runs.
8. Evidence Analyst answers multiple questions with exact quotes, locations, conflicts,
   and measured coverage.
9. Version Resolver selects the document valid at a requested date, not simply the
   newest filename.
10. Contact Monitor compares source-grounded contact and responsibility candidates
    across named snapshots and never deletes a missing contact automatically.
11. Artifact Studio renders validated claims consistently to five formats.
12. Platform Proof distinguishes offline capability, package readiness, transfer, and
   live cloud evidence instead of conflating them.

These contracts appear in five user-facing work areas rather than twelve disconnected
tiles. The Analysis Lab adds UC07 Research Notebook as a persistent orchestration layer:
one investigation can retain its goal, approved corpus, complete question/prompt set,
chosen reasoning route, and multiple verified run ledgers. It is not a ninth execution
workflow and does not persist transfer or action approval.

The browser console, CLI, and skill all submit the same `nemofold.job.v1` contract to
the same application service. That makes a visual demo useful without creating a
second, less safe implementation path.

## Why Nemotron and Nebius matter

The local core is intentionally useful on its own: inventory, extraction, indexing,
policy, citations, validation, journals, and artifacts are deterministic local work.
Nemotron is reserved for the part where language reasoning adds value across selected
context: synthesis, ambiguity handling, cross-document comparison, and drafting. A
Nebius-hosted runtime gives that isolated worker scalable inference without granting it
direct file-system authority.

This architecture makes the cloud contribution both meaningful and bounded. The live
adapter now validates the immutable package, records an atomic transfer attempt, calls
only the approved Token Factory origin, applies a conservative cost bound, and verifies
the returned request/response, usage, schema, and exact quotes. The real competition
call remains an explicit acceptance gate; the current repository does not claim a
completed transfer or `cloud_proof: true`.

## Existing work declaration

NemoFold is a new competition repository and implementation. It is informed by earlier
local document and folder-management prototypes, but its strict job contract, shared
application service, persistent evidence model, reversible action journal, privacy
package, validation rules, web console, and competition tests were built for this
project. Any final submission should retain this distinction and answer the Devpost
new-versus-existing field truthfully from the repository history.
