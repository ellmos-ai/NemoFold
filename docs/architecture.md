# Architecture

NemoFold uses a local-first hexagonal architecture. The application remains useful
offline; NemoClaw and Nemotron are adapters behind explicit privacy and cost gates.

```mermaid
flowchart LR
    U[Person] --> SURFACE[Web console / CLI / skill]
    SURFACE --> JOB[Strict job contract]
    JOB --> SURFACE
    SURFACE --> APP[Application service]
    APP --> POLICY[Policy and privacy gate]
    APP --> LEDGER[Run ledger, resume and verification]
    APP --> MODULES[Eight use-case modules]
    APP --> INV[Persistent inventory snapshots]
    MODULES --> EVIDENCE[Evidence engine]
    MODULES --> EXPORT[Artifact export]
    MODULES --> FILES[Local file ports]
    FILES --> LOCAL[(Approved local folders)]
    EVIDENCE --> INDEX[(Local FTS index)]
    FILES --> JOURNAL[Atomic action journal and undo]
    POLICY --> PACKAGE[Hashed, pseudonymized job package]
    PACKAGE --> ATTEMPT[Durable transfer attempt]
    ATTEMPT --> ADAPTER[Fail-closed Token Factory adapter]
    ADAPTER --> OPEN[NemoClaw / OpenShell sandbox - acceptance open]
    OPEN --> NEMO[NVIDIA Nemotron through Nebius]
    NEMO --> RESULT[Sanitized result and runtime evidence]
    RESULT --> VERIFY[Package, request, quote, usage and cost verifier]
    VERIFY --> EVIDENCE
    LEDGER --> AUDIT[(Run reports and artifact hashes)]
    JOURNAL --> AUDIT
```

Text alternative: a person calls one application service through the local web
console, CLI, or NemoFold skill. Every surface uses the same strict job contract. The
service invokes eight modules. Local policy, ledger, evidence, index, files, and export
components remain authoritative. Only an already approved job package can cross the
NemoClaw package route into an OpenShell sandbox and on to Nemotron. Immediately before
network I/O, an atomic attempt receipt makes a duplicate paid retry fail closed. The
answer returns through a verifier that recomputes the request and checks exact quotes,
usage, costs, endpoint, and hashes before it can become evidence.

The adapter and verifier are implemented and tested with simulated transports. The
actual NemoClaw/Nebius acceptance run remains open, so repository demos still record
`cloud_proof: false` unless a real successful result receipt exists. A user-supplied
NemoClaw version is stored only as declared metadata; `nemoclaw_proof` stays false until
a separate, sanitized sandbox-runtime record exists.
Likewise, generic run-report metadata can never promote itself to `cloud_proof: true`;
only the dedicated, hashed provider result-package contract is accepted for that claim.

The authoritative state is deterministic: job snapshots identify the request;
inventory snapshots identify the source set; the persistent index is updated by hash
and prunes deleted sources; the ledger records terminal status; action journals reconcile
crashes before a retry and generate verifiable undo receipts. Transfer-attempt receipts
also prevent an uncertain network failure from becoming an automatic second request.
External language-model output cannot directly mutate any authoritative layer.

See [NemoClaw integration](nemoclaw-integration.md) for the supported skill route and
the separate runtime-plugin route.
