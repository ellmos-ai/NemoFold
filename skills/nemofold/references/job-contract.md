# NemoFold sandbox job contract

Each uploaded job directory contains only regular files and exactly the files declared
by `manifest.json`, including at least:

- `manifest.json`: schema, run ID, hashes, expected files, and output filename.
- `job.json`: workflow, questions, artificial source descriptors, response schema,
  non-secret model/budget declaration, and the validation command.
- `context-receipts.json`: selected chunk IDs, artificial source IDs, and text.
- `privacy-receipt.json`: replacement counts and confirmation that host names and raw
  pseudonym mappings were not stored.

No file may contain an absolute host path, credential, environment dump, or undeclared
recipient. The sandbox result must use the same run ID and source IDs. The host re-hashes
the package and validates all returned quotes locally. It also rejects symlinks,
undeclared files, duplicate paths, changed hashes, host-path metadata, common secret
shapes, email addresses, IBANs, and remaining explicit sensitive terms.

The package is a transport contract, not permission to transmit. Upload or execution
requires a separate host-side gate. A preview package always records
`transfer_performed: false`.

Immediately before an approved request, the runner atomically creates the
manifest-declared `transfer-attempt.json`. It binds the run, model, endpoint, request
hash, and start time. A received response adds completion time, HTTP status, and
response hash. Its presence blocks automatic retry even if the process ended before a
result could be written.

After a received response, the second additional regular file is the manifest-declared
`result.json`. It uses `nemofold.live-result.v1` and contains:

Breaking pre-release contract change (2026-08-30): the former
`execution_environment` and `nemoclaw_version` fields were renamed to
`declared_execution_environment` and `declared_nemoclaw_version`, and
`nemoclaw_proof: false` became mandatory. Legacy field names are rejected explicitly.
Local `nemofold.live-result.v1` packages created before this change are pre-release
artifacts and are intentionally invalid under the current verifier; no public v1
contract has been released.

- the same run ID, response schema, provider, and model ID;
- `transfer_performed`, `cloud_proof`, status, and explicit errors;
- ordered answers whose citations are exact substrings of declared chunks;
- provider usage and current price inputs used for the bounded cost calculation;
- endpoint, timestamps, latency, explicitly declared environment metadata,
  `nemoclaw_proof: false`, and hashes of the sanitized request, response, and provider
  log;
- a sanitized request/response log without credentials or Authorization headers.

`python -m nemofold verify-result <job-directory>` revalidates both the immutable input
package, transfer attempt, and result. A provider failure may truthfully prove that a
transfer occurred, but it must set `cloud_proof: false`. A transport failure without a
response remains explicitly uncertain and requires manual reconciliation, never an
automatic paid retry.
