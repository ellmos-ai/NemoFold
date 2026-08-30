# Competition code map

All implementation files in this repository were created for the Nebius x NVIDIA Global
AI Hackathon after the submission window opened on 26 August 2026.

| Area | Classification | Purpose |
|---|---|---|
| `src/nemofold/` | NEW_CORE | Application contracts, cores, modules, CLI, and adapters |
| `skills/nemofold/` | NEW_CORE | NemoClaw-managed agent skill |
| `tests/` | GENERATED_OR_TEST_DATA | Unit, integration, and end-to-end verification |
| `examples/synthetic-home/` | GENERATED_OR_TEST_DATA | Synthetic, non-personal demo documents |
| `examples/jobs/` | GENERATED_OR_TEST_DATA | Public strict-job examples |
| `schemas/` | NEW_CORE | Machine-readable public job schema |
| `docs/` | NEW_CORE | Public architecture and integration documentation |

No pre-existing FolderHome source code is present in this repository. Historical ideas
informed the product scope, but the current checkout was built from a new empty Git
repository. The first implementation snapshot is Git commit
`2eaf011c4fb475028f2ac4428491027c7cd2fdb5`. The complete local workflow, recovery,
document-extraction, privacy-package, and verification audit is commit
`e8a221d0242cc6754dcc9fe9da27173970b89ccb`. The fail-closed Nebius Token Factory
adapter, durable transfer-attempt receipt, strict live-result verifier, CLI contract,
and adversarial tests are captured in commit
`562d47a1519c412e95cc2969241aadc04924b175`.
Runtime evidence declaration/proof separation, generic-report cloud-proof hardening,
cross-platform CI, packaging checks, and the associated adversarial tests are captured
in commit `c5dad72fbb744e9ef0218137f0f52bbbaf6b3e74`.
Reliable cross-origin rejection on Windows, including the bounded-body drain and JSON
error readback, is captured in commit `718e57b5ee4516d22895fc9e99f376c13a9e9989`.
The evidence-gated three-minute narration, architecture bridge, capture contract, and
cross-platform public-document guards are captured in commit
`ac20494a15330a05e0b81076ee4c42f5380558d9`.
The accessible, deterministic SVG export of the jury trust-boundary view is captured
in commit `f718d8ade06a3fc0e33e3bd1689921052bff105c`.
The three claim-safe jury design directions, their deterministic SVG/PNG generator, and
their manifest are captured in commit
`3e2cc158c07bb6a6f3a98d91042e9525637d9dfa`.
Whitespace-normalized, rerunnable design-asset output is captured in commit
`18fea5dba56dd5f5d9bc40206f494f8803644ec9`.
