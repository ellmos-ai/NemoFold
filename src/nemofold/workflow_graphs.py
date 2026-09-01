from __future__ import annotations

from collections.abc import Iterable

WORKFLOW_DESCRIPTIONS: dict[str, str] = {
    "cleanup_rules": (
        "Turn explicit cleanup corrections into readable rule suggestions, then apply only "
        "separately declared rules through dry-run, collision checks and the undo journal."
    ),
    "contact_monitor": (
        "Extract source-grounded contact and responsibility candidates, compare them with a "
        "named prior snapshot, and retain missing contacts for review instead of deleting them."
    ),
    "controlled_email": (
        "Build a local RFC 822 draft and an exact approval digest. Sending remains blocked until "
        "the digest is confirmed and a separately proven server adapter is configured."
    ),
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
    "mail_to_case": (
        "Read approved local EML files, preserve message provenance, and create a document case "
        "with a manifest, readable dossier and hash-recorded attachments."
    ),
    "platform_proof": (
        "Show connection and proof status while keeping local readiness, provider execution, "
        "Nebius competition evidence, and NemoClaw runtime evidence explicitly separate."
    ),
    "daily_arrivals": (
        "Compare a folder against a named snapshot and report each new file with its size, "
        "time, short content and owner, stating plainly where the platform cannot name one."
    ),
    "synopsis_merge": (
        "Merge several approved documents into one synopsis, keep the source and line behind "
        "every paragraph, and show disagreeing labels as conflict blocks instead of choosing."
    ),
    "fact_distill": (
        "Distil quotable facts from every approved source, strike duplicate statements from "
        "the findings, and keep each struck occurrence visible with the statement it repeats."
    ),
    "document_registry": (
        "Extract declared columns from every approved document into one table, anchor each "
        "filled cell to its source and line, and leave a cell empty when the sources are silent."
    ),
    "person_registry": (
        "Resolve the people the approved documents declare under named fields, keep every "
        "mention with its sentence, and write an identified, a pseudonymous and a local "
        "identity-map artifact."
    ),
    "relation_model": (
        "Derive links between declared people only from sentences that state them, mark "
        "being named together as exactly that, and render a deterministic graph."
    ),
    "person_timeline": (
        "Place every stated time on a lane per person, attribute a statement only where a "
        "document declares its speaker, and keep an unstated time undetermined."
    ),
    "coverage_timeline": (
        "Read declared coverage intervals out of contract documents, leave an unnamed end "
        "open, and report a start date that cannot be read instead of inventing one."
    ),
    "alibi_weave": (
        "Separate a self-reported position from one another source confirms at the same "
        "place and time, and report every person nothing places as a gap."
    ),
    "contradiction_synopsis": (
        "Put disagreeing statements side by side in both wordings with their anchors, and "
        "name which sources disagree rather than deciding which is right."
    ),
    "corpus_query": (
        "Answer one narrow question over a large corpus through staged aggregation, keeping "
        "every match a quoted sentence with the sources it came from."
    ),
    "web_research": (
        "Search the open web behind four separate gates and keep only what came back "
        "with an address, refusing any query that would carry private content out."
    ),
    "dossier": (
        "Assemble cited search results on a declared subject into a reading list that "
        "says in the artifact that it is not a finding about anybody."
    ),
    "bundle_completeness_check": (
        "Report whether every approved source was read, whether the required formats can "
        "be produced and whether a required part came out empty, concluding nothing "
        "about content."
    ),
    "print_action": (
        "Prepare a print-ready file and the exact command to print it, and state that "
        "the printing itself is the person's step because no receipt comes back from it."
    ),
    "reference_check": (
        "Check the approved sources against a declared checklist, quote the line that "
        "answers each item, and list what is missing without judging whether the "
        "document is correct or sufficient."
    ),
    "rater_race": (
        "Code the same material twice under two readings and report where they part, "
        "with percent agreement and kappa side by side because the first number "
        "alone is misleading whenever one code dominates."
    ),
    "guide_compose": (
        "Fold a corpus into one guide that stands in for its documents, keeping every "
        "paragraph a quoted line with its source and reporting how many repeats were "
        "folded."
    ),
    "wiki_export": (
        "Write the corpus as a walkable wiki with one page per document and an index, "
        "carrying each document unchanged rather than summarising it."
    ),
    "pattern_mining": (
        "Report which lines recur across a large set, with how often and from where, "
        "through the staged aggregation that keeps the anchors."
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
    "cleanup_rules": (
        ("scan", "Scan", "approved cleanup set"),
        ("corrections", "Corrections", "explicit user examples"),
        ("suggest", "Suggest", "readable suffix rules"),
        ("preview", "Dry run", "declared rules only"),
        ("collision", "Preflight", "targets + collisions"),
        ("gate", "Action gate", "immediate authority"),
        ("journal", "Apply + undo", "reversible moves"),
    ),
    "contact_monitor": (
        ("extract", "Extract", "approved documents + EML"),
        ("candidates", "Candidates", "email + role evidence"),
        ("compare", "Compare", "named prior snapshot"),
        ("review", "Review", "new + changed + missing"),
        ("retain", "Retain", "no automatic deletion"),
    ),
    "controlled_email": (
        ("compose", "Compose", "local RFC 822 draft"),
        ("attachments", "Attach", "approved source IDs"),
        ("digest", "Approval digest", "exact content identity"),
        ("gate", "Send gate", "immediate confirmation"),
        ("adapter", "Mail adapter", "server-proven transport"),
        ("receipt", "Receipt", "sent or honestly blocked"),
    ),
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
    "mail_to_case": (
        ("inventory", "Inventory", "approved local EML"),
        ("parse", "Parse", "headers + plain body"),
        ("attachments", "Attachments", "safe names + hashes"),
        ("case", "Case dossier", "source-grounded thread"),
        ("manifest", "Manifest", "omissions + provenance"),
    ),
    "platform_proof": (
        ("local", "Local core", "ready or unavailable"),
        ("provider", "Provider", "execution receipt"),
        ("nebius", "Nebius", "competition proof"),
        ("nemoclaw", "NemoClaw", "runtime proof"),
        ("report", "Status ledger", "no inferred proof"),
    ),
    "daily_arrivals": (
        ("operation", "Inventory", "approved corpus"),
        ("gate", "Baseline", "named snapshot"),
        ("operation", "Arrivals", "name + size + content"),
        ("operation", "Owner", "or the reason why not"),
        ("operation", "Routine", "task file you install"),
    ),
    "synopsis_merge": (
        ("operation", "Inventory", "approved corpus"),
        ("operation", "Sections", "heading-wise"),
        ("operation", "Merge", "anchor per paragraph"),
        ("gate", "Conflicts", "both readings kept"),
        ("operation", "Export", "selected formats"),
    ),
    "person_registry": (
        ("operation", "Inventory", "approved corpus"),
        ("operation", "Declare", "named fields only"),
        ("operation", "Resolve", "spellings and titles"),
        ("gate", "Pseudonymize", "identity map stays local"),
        ("operation", "Export", "identified and pseudonymous"),
    ),
    "relation_model": (
        ("operation", "Resolve", "declared people"),
        ("operation", "Read", "sentences naming two"),
        ("gate", "Require quote", "no sentence, no edge"),
        ("operation", "Render", "deterministic graph"),
    ),
    "person_timeline": (
        ("operation", "Inventory", "approved corpus"),
        ("operation", "Extract", "stated times"),
        ("gate", "Undetermined", "never a guessed moment"),
        ("operation", "Render", "one lane per person"),
    ),
    "coverage_timeline": (
        ("operation", "Read", "declared contract fields"),
        ("gate", "Open end", "unnamed end stays open"),
        ("operation", "Render", "intervals over time"),
    ),
    "alibi_weave": (
        ("operation", "Collect", "stated positions"),
        ("gate", "Corroborate", "other source, place and time"),
        ("operation", "Gaps", "nobody places this person"),
        ("operation", "Render", "one line, two lines, hatching"),
    ),
    "contradiction_synopsis": (
        ("operation", "Merge", "section by section"),
        ("operation", "Compare", "declared contested terms"),
        ("gate", "Keep both", "no reading is dropped"),
        ("operation", "Export", "selected formats"),
    ),
    "corpus_query": (
        ("operation", "Select", "sentences matching the question"),
        ("operation", "Partition", "deterministic, fixed size"),
        ("operation", "Fold", "twice, anchors preserved"),
        ("gate", "Quote only", "no match means no answer"),
    ),
    "web_research": (
        ("gate", "Preflight", "no private content in a query"),
        ("gate", "Approve", "server, call, adapter key"),
        ("operation", "Search", "declared queries only"),
        ("operation", "Keep", "results with an address"),
    ),
    "dossier": (
        ("gate", "Subject", "declared, never inferred"),
        ("operation", "Search", "through the same four gates"),
        ("operation", "Assemble", "a cited reading list"),
        ("gate", "No verdict", "nothing is weighed or concluded"),
    ),
    "bundle_completeness_check": (
        ("operation", "Read", "every approved source"),
        ("gate", "Complete", "read, producible, non-empty"),
        ("operation", "Report", "what passed and what did not"),
    ),
    "guide_compose": (
        ("operation", "Merge", "section by section"),
        ("operation", "Fold", "repeated paragraphs"),
        ("gate", "Quoted only", "nothing is rewritten"),
    ),
    "wiki_export": (
        ("operation", "Page", "one per document"),
        ("operation", "Index", "links every page"),
        ("gate", "Unchanged", "no page disagrees with its file"),
    ),
    "pattern_mining": (
        ("operation", "Lift", "quotable statements"),
        ("operation", "Aggregate", "staged, anchors kept"),
        ("gate", "Support", "below the threshold is not a pattern"),
    ),
    "rater_race": (
        ("operation", "Declare", "the coding scheme"),
        ("operation", "Code twice", "two independent readings"),
        ("operation", "Diff", "cell by cell"),
        ("gate", "Two numbers", "agreement and kappa, never one"),
    ),
    "reference_check": (
        ("operation", "Declare", "the checklist to compare against"),
        ("operation", "Match", "quote the answering line"),
        ("gate", "No verdict", "present or absent, never correct"),
    ),
    "print_action": (
        ("operation", "Select", "one approved source"),
        ("operation", "Prepare", "print-ready file"),
        ("gate", "Not printed", "no receipt comes back"),
    ),
    "fact_distill": (
        ("operation", "Inventory", "approved corpus"),
        ("operation", "Distil", "quotable sentences"),
        ("gate", "Dedupe", "exact or normalized"),
        ("operation", "Appendix", "struck occurrences"),
        ("operation", "Export", "selected formats"),
    ),
    "document_registry": (
        ("operation", "Inventory", "approved corpus"),
        ("operation", "Columns", "declared contract"),
        ("operation", "Extract", "labelled lines only"),
        ("gate", "Anchor", "source + line per cell"),
        ("operation", "Table", "json + csv + report"),
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
