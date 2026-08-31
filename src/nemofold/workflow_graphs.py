from __future__ import annotations

from collections.abc import Iterable

WORKFLOW_DESCRIPTIONS: dict[str, str] = {
    "bundle_export": (
        "Build a deterministic document bundle, manifest, omission list, and integrity hashes "
        "without changing the source files."
    ),
    "evidence_analyst": (
        "Build a traceable evidence bundle, select and anonymize relevant context, then "
        "investigate large approved corpora under every queued question or prompt."
    ),
    "folder_digest": (
        "Run a repeatable folder routine: compare inventories, resolve version families, "
        "and publish a source-grounded digest of additions, changes, stable files, and deletions."
    ),
    "platform_proof": (
        "Show connection and proof status while keeping local readiness, provider execution, "
        "Nebius competition evidence, and NemoClaw runtime evidence explicitly separate."
    ),
    "report_studio": (
        "Render an already validated analysis into consistent Markdown, text, PDF, DOCX, and "
        "ODT artifacts with the same source references."
    ),
    "smart_inbox": (
        "Open the Document Center, apply its Storage Policies to the complete inbox batch, check "
        "collisions, and perform only explicitly authorized reversible actions."
    ),
    "storage_policy": (
        "Resolve naming, format, original-handling, and retention rules into a previewable plan "
        "with collision checks and undo receipts."
    ),
    "version_resolver": (
        "Group related documents, determine the version valid at the requested date, and expose "
        "the comparison evidence and remaining uncertainty."
    ),
}


WORKFLOW_STEPS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "bundle_export": (
        ("inventory", "Inventory", "approved sources"),
        ("extract", "Extract", "supported text"),
        ("sort", "Order", "deterministic sequence"),
        ("bundle", "Bundle", "combined content"),
        ("manifest", "Manifest", "omissions + hashes"),
        ("verify", "Verify", "integrity check"),
    ),
    "evidence_analyst": (
        ("inventory", "Inventory", "approved corpus"),
        ("bundle", "Evidence bundle", "manifest + hashes"),
        ("index", "Index", "local search memory"),
        ("retrieve", "Retrieve", "per queued task"),
        ("anonymize", "Anonymize", "local pseudonyms"),
        ("worker", "Analyze", "large-data worker"),
        ("validate", "Validate", "quotes + claims"),
        ("report", "Report", "coverage + gaps"),
    ),
    "folder_digest": (
        ("delta", "Delta scan", "new + changed + deleted"),
        ("cards", "Document cards", "local inventory"),
        ("versions", "Version resolve", "families + validity"),
        ("synthesize", "Synthesize", "bounded digest"),
        ("validate", "Source check", "coverage + gaps"),
        ("report", "Digest", "versioned artifact"),
    ),
    "platform_proof": (
        ("local", "Local core", "ready or unavailable"),
        ("provider", "Provider", "execution receipt"),
        ("nebius", "Nebius", "competition proof"),
        ("nemoclaw", "NemoClaw", "runtime proof"),
        ("report", "Status ledger", "no inferred proof"),
    ),
    "report_studio": (
        ("input", "Validated report", "claims + coverage"),
        ("model", "Document model", "format-neutral"),
        ("render", "Render", "selected formats"),
        ("hash", "Hash", "artifact integrity"),
        ("verify", "Open test", "consistent sources"),
    ),
    "smart_inbox": (
        ("scan", "Scan", "approved inbox"),
        ("policy", "Storage policy", "name + retain + route"),
        ("classify", "Classify", "full-batch proposal"),
        ("collision", "Preflight", "routes + collisions"),
        ("gate", "Action gate", "explicit authority"),
        ("apply", "Apply", "reversible changes"),
        ("report", "Journal", "run + undo receipt"),
    ),
    "storage_policy": (
        ("resolve", "Resolve rules", "global + local"),
        ("preview", "Preview", "planned changes"),
        ("collision", "Collision test", "fail closed"),
        ("gate", "Action gate", "explicit authority"),
        ("apply", "Apply", "move + copy + convert"),
        ("undo", "Undo receipt", "recoverable state"),
    ),
    "version_resolver": (
        ("candidates", "Candidates", "approved documents"),
        ("families", "Families", "related versions"),
        ("compare", "Compare", "content + dates"),
        ("validity", "Validity", "requested date"),
        ("matrix", "Change matrix", "evidence + uncertainty"),
    ),
}


def workflow_graphs(workflows: Iterable[str] | None = None) -> tuple[dict[str, object], ...]:
    selected = set(WORKFLOW_STEPS) if workflows is None else set(workflows)
    graphs: list[dict[str, object]] = []
    for workflow in WORKFLOW_STEPS:
        if workflow not in selected:
            continue
        steps = WORKFLOW_STEPS[workflow]
        nodes = [
            {
                "id": node_id,
                "label": label,
                "detail": detail,
                "kind": (
                    "privacy"
                    if node_id == "anonymize"
                    else "worker"
                    if node_id == "worker"
                    else "gate"
                    if node_id in {"gate", "policy"}
                    else "operation"
                ),
                "anonymization": node_id == "anonymize",
                "position": [index * 220, 0],
            }
            for index, (node_id, label, detail) in enumerate(steps)
        ]
        connections = [
            {"from_node": steps[index][0], "to_node": steps[index + 1][0]}
            for index in range(len(steps) - 1)
        ]
        graphs.append(
            {
                "workflow": workflow,
                "description": WORKFLOW_DESCRIPTIONS[workflow],
                "contains_anonymization": any(node["anonymization"] for node in nodes),
                "nodes": nodes,
                "connections": connections,
            }
        )
    return tuple(graphs)
