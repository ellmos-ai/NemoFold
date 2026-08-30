# NemoClaw integration

NemoFold separates three extension types:

1. The **NemoFold application** owns contracts, local policy, evidence, files, and reports.
2. The **NemoFold agent skill** teaches a sandboxed agent how to process a bounded job.
3. A future **OpenClaw runtime plugin** could add in-process hooks or tools, but is not
   required for the first functional integration.

The supported skill package is in `skills/nemofold/`. NVIDIA documents installation as:

```bash
nemoclaw <sandbox-name> skill install ./skills/nemofold/
```

The current host-side job route is intentionally explicit:

```powershell
python -m nemofold package --job examples\jobs\nemoclaw-package.json `
  --allow-root $PWD --run-id proof_1 --allow-external-models `
  --max-external-cost-usd 1.0
python -m nemofold verify-job run-reports\nemoclaw-package\nemoclaw-packages\proof_1
```

This only creates and validates a local package. Its output states
`transfer_performed: false`; it does not contact Nebius or NemoClaw. Upload and sandbox
execution are separate, human-controlled commands:

```bash
nemoclaw <sandbox-name> upload ./job-package /sandbox/nemofold/jobs/<run-id>
nemoclaw <sandbox-name> exec --workdir /sandbox/nemofold/app -- \
  python -m nemofold verify-job /sandbox/nemofold/jobs/<run-id>
```

The live spike must use the exact commands supported by the installed NemoClaw version,
record `nemoclaw --version`, and preserve verbatim sanitized output. The application
must reject an answer whose run ID, source IDs, schema, or evidence locators do not match
the uploaded package.

NVIDIA's current plugin guide describes OpenClaw plugins as version-matched code packages
baked into a full custom runtime image. It also says that managed plugin lifecycle is not
yet available. NemoFold therefore does not mislabel its `SKILL.md` bundle as a plugin.

Official references:

- https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/reference/commands
- https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/manage-sandboxes/state-and-backups/understand-sandbox-state
- https://docs.nvidia.com/nemoclaw/user-guide/openclaw/manage-sandboxes/install-openclaw-plugins
