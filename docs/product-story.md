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

NemoFold separates durable authority from optional reasoning. Its five shared cores
serve eight practical workflow chains:

1. Smart Inbox routes new files after a full-batch collision and policy preflight.
2. Storage Policies name, retain, move, copy, or convert files with dry-run and undo.
3. Bundle Export creates deterministic document packages with manifests and hashes.
4. Folder Digest records what is new, changed, stable, or deleted across runs.
5. Evidence Analyst answers multiple questions with exact quotes, locations, conflicts,
   and measured coverage.
6. Version Resolver selects the document valid at a requested date, not simply the
   newest filename.
7. Artifact Studio renders validated claims consistently to five formats.
8. Platform Proof distinguishes offline capability, package readiness, transfer, and
   live cloud evidence instead of conflating them.

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
adapter and its measured output are still an explicit acceptance gate; the current
repository does not claim a completed transfer or `cloud_proof: true`.

## Existing work declaration

NemoFold is a new competition repository and implementation. It is informed by earlier
local document and folder-management prototypes, but its strict job contract, shared
application service, persistent evidence model, reversible action journal, privacy
package, validation rules, web console, and competition tests were built for this
project. Any final submission should retain this distinction and answer the Devpost
new-versus-existing field truthfully from the repository history.
