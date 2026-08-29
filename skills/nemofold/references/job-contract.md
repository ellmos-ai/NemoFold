# NemoFold sandbox job contract

Each uploaded job directory contains only regular files and at least:

- `manifest.json`: schema, run ID, hashes, expected files, and output filename.
- `job.json`: workflow, questions, artificial source descriptors, response schema, and
  non-secret model/budget declaration.
- `context-receipts.json`: selected chunk IDs, artificial source IDs, and text.

No file may contain an absolute host path, credential, environment dump, or undeclared
recipient. The sandbox result must use the same run ID and source IDs. The host re-hashes
the package and validates all returned quotes locally.
