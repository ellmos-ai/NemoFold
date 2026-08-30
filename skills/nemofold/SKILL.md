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

1. Validate the package with `python -m nemofold verify-job <job-directory>`.
2. Stop unless the host separately supplied its explicit live-transfer approval and
   current price inputs. Merely receiving a package is not approval.
3. When approved, run exactly one `python -m nemofold token-factory-run` command for the
   supplied directory. Never add or redirect an endpoint, and never put the key on the
   command line; the host provides `NEBIUS_API_KEY` through the process environment.
4. For every question, use only the listed chunks. Return claims in the response schema;
   every claim must include an exact quote, chunk ID, and source ID. Mark conflicts and
   uncertainty explicitly.
5. Write only the declared `transfer-attempt.json` and `result.json`. The runner writes
   the attempt atomically before network I/O and refuses a second paid request when
   either file already exists. Never delete an uncertain attempt to retry automatically.
6. Run `python -m nemofold verify-result <job-directory>`. A failed hash, locator, schema,
   package, endpoint, cost, or usage check is a failed job, not a warning.
7. Report the final status and output path; do not claim host acceptance or NemoClaw
   execution merely from locally supplied version metadata.

## Prohibited shortcuts

- No general web search for missing document facts.
- No unsupported claim without an `unverified` status.
- No file move, rename, deletion, mail, upload, or publication.
- No statement that NemoClaw or Nebius succeeded unless the current command output proves it.
- No deletion of `transfer-attempt.json` or `result.json` to bypass the exactly-once
  guard.

See `references/job-contract.md` for the package contract.
