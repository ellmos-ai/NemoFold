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

Document Services wave 1 - the `document_registry`, `fact_distill`, `synopsis_merge`
and `daily_arrivals` workflows with their modules, contracts, console cards and
Captain's Desk intents - is classified NEW_CORE. The ellmos and BACH document-analysis
sources on this machine were read as prior art for the shape of the problem; no code
was copied from them, and each workflow was written against NemoFold's own job
contract, evidence and coverage machinery.

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
The public-release security hardening, provider-response redaction, stored action-plan
revalidation, governance documents, and 132-test local acceptance are captured in
commit `f3f47d700c3daa39f6dd38f5365fe59dc9507c02`.
The provider-neutral evidence core, Ollama and LM Studio adapters, personal Codex and
Claude Code bridges, official OpenAI and Anthropic API adapters, shared CLI/loopback
HTTP/MCP surfaces, finite budget gates, quote-bound receipts, and 182-test local
acceptance are captured in commit
`9cc9d4380725a5f707517cc28b6a5ed8a3d9dfc2`.

The independent review hardening (network-exposed job surfaces refused, DNS-rebinding
host check, bounded socket reads, scoped report verification, packaged theme scenes,
drained early rejections) spans commits `966cf50` through `7fa6777`.
The live model-catalog confirmation before the durable transfer receipt and the
documented-parameters-only request body are captured in commit `5b1ccd5`.
The routed room redesign (per-area home modules, engine-room drawer, instrument
sprite, ship's-chart fold-out, scene artwork with recorded provenance) spans commits
`d59f0be` through `f6ef7e2` and `24fb23c` through `5b701b8`.
The Captain's Desk planner (deterministic intent tables, voyage drafts that plan but
never execute) is captured in commits `fd3213d` through `5e1abdb`.
Wave one of the document services (document_registry, fact_distill, synopsis_merge,
daily_arrivals) and the shared anchored primitives layer are captured in commits
`1e75668` through `d984fbf`.
The use-case library (shipped path-free specialists, model-preference authority with
its hard exposure cap, kept reservations, chain runs with one dossier) is captured in
commits `d0fee5c` through `e5ee10e`.
The consolidated information architecture (Folders, Processes and Workflows with
tag-filtered use cases, the instrument registry and the artifact catalog, Governance
with its policy and rule registers) is captured in commits `13ffe46` through
`a01a572`. All of the above was written for this competition after 26 August 2026;
scene artwork provenance is recorded in docs/media/designset/README.md.
The Case Chronicle - staged aggregation with anchor preservation, the declared-only
person registry with its pseudonymous export and local identity map, timelines that
carry undetermined times as undetermined, corroboration that keeps a self-report and an
outside confirmation on separate lines, deterministic claim-safe SVG, seven composing
workflows and the fictional synthetic case they are all tested on - is captured in the
commits of the WP-CHRONICLE-1 series. The synthetic case in `examples/synthetic-case/`
is invented in full; every document says so in its first line.
Wave two of the Document Services - structured local sources read as anchored
corpus text, a gated web-research schiene with a Tavily adapter that is only ever
exercised against local mocks in tests, delivery rules that file artifacts inside
the approved roots, a byte-stable workbook writer, a print-ready export that does
not invoke a printer, structured needs_user_input, a bundle completeness check,
and D-035 rights evaluated in the mail path with recipient classes and a
class-break rule - is captured in the commits of the WP-DOCSERV-2 series. No test
in that series reaches the network or opens a mail socket; real transmission
remains a user gate.
Wave four - the reference check that quotes what answers each item and refuses to
judge the document, the two-reading rater race with percent agreement and Cohen's
kappa side by side, guide and wiki composition on the existing primitives, pattern
mining over the staged aggregation, and the optional report-forge adapter for filling
.docx templates - is captured in the commits of the WP-FINISH-1 series. report-forge
is a dependency behind the `templates` extra and is not vendored; it is pinned to a
commit because the repository publishes no release tags. The synthetic questionnaire
and log fixtures are invented in full and say so in their first line.
The proven Token Factory run of 2026-09-02 - the real paid call to
`nvidia/nemotron-3-super-120b-a12b` over the fictional synthetic case - is captured
in commits `cff7355` through `a1080ba` (four live-run fixes, each provoked by an
actual fail-closed rejection: the endpoint's `max_tokens` wire field, a prompt
hardening after the verifier caught two misattributed quotes, per-receipt scoping of
the chunk-uniqueness rule, and binding the three usage counters while tolerating
additive provider detail fields) plus the committed receipt chain in
`examples/proven-run/`, which `python -m nemofold verify-result examples/proven-run`
re-verifies offline. The package contains no secrets and no real personal data.
