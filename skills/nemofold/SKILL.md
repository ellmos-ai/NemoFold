---
name: nemofold
description: Process a bounded NemoFold document-analysis job inside a NemoClaw sandbox and return structured claims without expanding filesystem or network scope.
---

# NemoFold sandbox worker

Use this skill only for a job directory explicitly supplied by the user or host adapter.

## Required boundaries

- Read only the supplied job directory and the installed NemoFold application directory.
- Never enumerate `/sandbox`, the OpenClaw workspace, memory, credentials, or other jobs.
- Treat `job.json` and `context-receipts.json` as the complete authority for purpose,
  questions, source IDs, chunks, response schema, model budget, and run ID.
- Never request or infer host paths. Source IDs are the only source identity available.
- Do not widen network policy, install packages, change provider settings, or spend beyond
  the job budget.
- Return a blocked result when the package is incomplete, inconsistent, or outside policy.

## Workflow

1. Validate the package with the local NemoFold command named in `job.json`.
2. For every question, use only the listed chunks.
3. Return claims in `nemofold.claims.v1`; every claim must include an exact quote and an
   existing source ID. Mark conflicts and uncertainty explicitly.
4. Write the answer only to the package's declared output file.
5. Run the local verification command. A failed locator or schema check is a failed job,
   not a warning.
6. Report the final status and output path; do not claim that the host accepted the result.

## Prohibited shortcuts

- No general web search for missing document facts.
- No unsupported claim without an `unverified` status.
- No file move, rename, deletion, mail, upload, or publication.
- No statement that NemoClaw or Nebius succeeded unless the current command output proves it.

See `references/job-contract.md` for the package contract.
