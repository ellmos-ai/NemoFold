# Architecture

NemoFold uses a local-first hexagonal architecture. The application remains useful
offline; NemoClaw and Nemotron are adapters behind explicit privacy and cost gates.

```mermaid
flowchart LR
    U[Person] --> CLI[CLI / skill]
    CLI --> JOB[Strict job contract]
    JOB --> CLI
    CLI --> APP[Application service]
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
    POLICY --> ADAPTER[NemoClaw job adapter - live proof open]
    ADAPTER --> OPEN[NemoClaw / OpenShell sandbox - live proof open]
    OPEN --> NEMO[Nemotron through Nebius - live proof open]
    NEMO --> ADAPTER
    ADAPTER --> EVIDENCE
    LEDGER --> AUDIT[(Run reports and artifact hashes)]
    JOURNAL --> AUDIT
```

Text alternative: a person calls one application service through the CLI or the
NemoFold skill. The service invokes eight modules. Local policy, ledger, evidence,
index, files, and export components remain authoritative. Only an already approved job
package can cross the NemoClaw adapter into an OpenShell sandbox and on to Nemotron.
The answer returns to the local evidence engine before it can become a report.

The external nodes are design commitments, not yet live evidence. The offline demo
therefore records `cloud_proof: false`.

The authoritative state is deterministic: job snapshots identify the request;
inventory snapshots identify the source set; the persistent index is updated by hash
and prunes deleted sources; the ledger records terminal status; action journals reconcile
crashes before a retry and generate verifiable undo receipts. External language-model
output cannot directly mutate any of these layers.

See [NemoClaw integration](nemoclaw-integration.md) for the supported skill route and
the separate runtime-plugin route.
