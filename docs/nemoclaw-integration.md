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
`transfer_performed: false`; it does not contact Nebius or NemoClaw.

The implemented Token Factory worker remains a separate, human-controlled step:

```powershell
$env:NEBIUS_API_KEY = "<session-only-key>"
python -m nemofold token-factory-preflight <job-package> `
  --input-price-usd-per-million <current-input-rate> `
  --output-price-usd-per-million <current-output-rate>
python -m nemofold token-factory-run <job-package> `
  --approve-live-transfer `
  --input-price-usd-per-million <current-input-rate> `
  --output-price-usd-per-million <current-output-rate> `
  --declared-nemoclaw-version <captured-installed-version>
python -m nemofold verify-result <job-package>
Remove-Item Env:\NEBIUS_API_KEY
```

The approval flag, current provider rates, valid immutable package, official endpoint,
and cost ceiling are all mandatory. The worker rejects redirects and duplicate
attempt/result files. It atomically records `transfer-attempt.json` before network I/O,
so a connection loss cannot silently authorize a duplicate paid request. The result
verifier recomputes the exact request from the package, checks output quotes against
supplied chunks, and binds the attempt plus sanitized request/response logs to hashes.
The request uses the Token Factory chat API's documented `json_object` mode, includes
the complete result schema inside the bounded user payload, and enforces that schema
locally after the response. This avoids relying on model-specific server-side
`json_schema` support.
The preflight command performs the same local package, endpoint, model, request, cost,
budget, and duplicate-attempt checks without contacting Nebius or creating a durable
attempt. It reports key presence only as a boolean and still requires the separate
live-transfer approval flag for execution.
Supplying `--declared-nemoclaw-version` records self-declared environment metadata. The
result always keeps `nemoclaw_proof: false`; the value is not, by itself, evidence that
NemoClaw executed the command.

Uploading and sandbox execution are separate, human-controlled commands:

```bash
nemoclaw <sandbox-name> upload ./job-package /sandbox/nemofold/jobs/<run-id>
nemoclaw <sandbox-name> exec --workdir /sandbox/nemofold/app -- \
  python -m nemofold verify-job /sandbox/nemofold/jobs/<run-id>
```

The live acceptance run must use the exact commands supported by the installed NemoClaw
version, record `nemoclaw --version`, and preserve verbatim sanitized output alongside
the validated result. The implemented verifier rejects an answer whose run ID, source
IDs, schema, request, usage, cost, or evidence locators do not match the package.

NVIDIA's current plugin guide describes OpenClaw plugins as version-matched code packages
baked into a full custom runtime image. It also says that managed plugin lifecycle is not
yet available. NemoFold therefore does not mislabel its `SKILL.md` bundle as a plugin.

Official references:

- https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/reference/commands
- https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/manage-sandboxes/state-and-backups/understand-sandbox-state
- https://docs.nvidia.com/nemoclaw/user-guide/openclaw/manage-sandboxes/install-openclaw-plugins
- https://docs.tokenfactory.nebius.com/api-reference/introduction
- https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion
- https://docs.tokenfactory.nebius.com/ai-models-inference/json
