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
