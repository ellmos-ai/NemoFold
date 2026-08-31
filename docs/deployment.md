# Capability-minimal demo deployment

The repository includes a provider-neutral OCI/Docker definition for the public
synthetic demo. It deliberately starts `serve-demo`, not the locally authoritative
`serve` command. Visitors can exercise the five read-only workflows over the committed
synthetic corpus, but cannot select host paths, enable actions, supply model authority,
or change the privacy and budget policy.

## Local container smoke test

```powershell
docker build --tag nemofold-demo:local .
docker run --rm `
  --read-only `
  --tmpfs /tmp:rw,nosuid,nodev,size=64m `
  --cap-drop ALL `
  --security-opt no-new-privileges:true `
  --publish 127.0.0.1:8080:8080 `
  nemofold-demo:local
```

Open <http://127.0.0.1:8080>. The health endpoint is
<http://127.0.0.1:8080/api/status>. It must report all of the following before a
deployment is accepted:

```json
{
  "ok": true,
  "mode": "public-synthetic-demo",
  "public_demo": true,
  "read_only": true,
  "synthetic_only": true,
  "cloud_proof": false,
  "transfer_performed": false
}
```

The image uses an unprivileged numeric user, copies only the package and synthetic demo
corpus, and writes transient job output below the system temporary directory. The run
command above makes the rest of the container read-only and supplies a bounded temporary
filesystem.

## Hosting contract

- Deploy the `Dockerfile` as an OCI-compatible web service.
- Route the provider's public port to `PORT` (default `8080`).
- Keep `NEMOFOLD_MAX_PARALLEL_JOBS` low (default `2`) until capacity is measured.
- Do not inject `NEBIUS_API_KEY` or mount personal folders into this public image.
- Require HTTPS at the hosting edge and retain the same-origin request checks.
- Use `/api/status` for health checks and capture its JSON plus the deployed image digest.
- Run one workflow through the public URL and retain the sanitized result as acceptance
  evidence before calling the demo deployed.

This package is deployment-ready, but the repository does not claim a hosted URL or a
successful container build until those facts are independently read back. Deployment is
an external action and remains an explicit user gate.
