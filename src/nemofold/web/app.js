const $ = (id) => document.getElementById(id);
const lines = (value) => value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
let publicDemo = false;
let folderPickerEnabled = false;
let providerSurfaceEnabled = false;
let externalModelsAllowed = false;
let providerContracts = new Map();
let workflowGraphs = new Map();
let previousProviderId = "";
let folderTargetId = null;
let folderCurrentPath = null;
let artifactSurfaceEnabled = false;
let draftSurfaceEnabled = false;
let notebookSurfaceEnabled = false;
let currentNotebookId = null;
let activeRequest = false;
let promptLibraryView = "catalog";
const promptCatalogKey = "nemofold.prompt-catalog.v1";
const promptHistoryKey = "nemofold.prompt-history.v1";
const analysisScaleDefaults = {
  focused: {maxChunks: 16, outputTokens: 4096, timeoutSeconds: 600},
  deep: {maxChunks: 64, outputTokens: 16384, timeoutSeconds: 1200},
  corpus: {maxChunks: 256, outputTokens: 32768, timeoutSeconds: 1800}
};
const builtInPromptCatalog = [
  {
    id: "evidence-audit",
    name: "Evidence audit",
    items: [
      "Which claims are directly supported by the approved sources?",
      "Give exact quotes and source locations for every supported claim.",
      "Which requested points remain unsupported or unread?"
    ]
  },
  {
    id: "conflict-map",
    name: "Conflict and change map",
    items: [
      "Which documents contradict each other?",
      "Which wording changed across versions and when?",
      "Which source is valid at the requested date?"
    ]
  },
  {
    id: "large-corpus-synthesis",
    name: "Large corpus synthesis",
    items: [
      "Identify the recurring themes across the entire approved corpus.",
      "Separate consensus, minority positions, contradictions and evidence gaps.",
      "Produce a source-grounded synthesis with exact citations for each conclusion."
    ]
  }
];
const providerModelDefaults = {
  ollama: "qwen3:4b",
  "lm-studio": "local-model",
  "codex-cli": "gpt-5.4",
  "claude-code": "sonnet",
  openai: "",
  anthropic: ""
};
const workflowDefaults = {
  cleanup_rules: {
    questions: [],
    parameters: {rules: [], corrections: [], min_support: 2, allowed_extensions: [".txt", ".md"], naming_template: "{stem}{suffix}", original_policy: "move", retention_action: "keep"},
    hint: "Cleanup Rules learns only readable suggestions from explicit corrections. Suggestions never activate themselves; declared rules run through dry-run, collision checks and undo receipts."
  },
  mail_to_case: {
    questions: [],
    parameters: {case_id: "new-case", case_title: "NemoFold mail case", include_attachments: true},
    hint: "Mail-to-Case reads approved local .eml files and creates a provenance manifest, readable dossier and hash-recorded attachments without changing the source messages."
  },
  controlled_email: {
    questions: [],
    parameters: {from_address: "sender@example.org", to: ["recipient@example.org"], cc: [], subject: "Review draft", body: "Please review the attached material.", attachment_source_ids: [], send_requested: false},
    hint: "Controlled Email creates a local RFC 822 draft and approval digest. Actual sending stays blocked until that exact digest is confirmed and a server-side mail adapter is proven."
  },
  contact_monitor: {
    questions: [],
    parameters: {},
    hint: "Contact Monitor extracts email and responsibility candidates with source quotes, compares a named earlier snapshot and never auto-deletes missing contacts."
  },
  evidence_analyst: {
    questions: ["When does the current policy begin?", "Which earlier wording changed?"],
    parameters: {max_chunks: 256, formats: ["md", "txt"], conflict_scan: true},
    hint: "Evidence Analyst searches the approved inputs and reports exact source locations, conflicts and coverage."
  },
  folder_digest: {
    questions: [],
    parameters: {digest_depth: "full", summary_length: 3},
    hint: "Folder Digest compares the current inventory with a prior run and makes additions, changes and deletions visible."
  },
  bundle_export: {
    questions: [],
    parameters: {bundle_format: "text", bundle_name: "web_bundle", include_manifest: true, order: "display_name", recursive: true},
    hint: "Bundle Export creates a deterministic text bundle, manifest and integrity hashes without changing the sources."
  },
  version_resolver: {
    questions: [],
    parameters: {fallback_to_file_time: true},
    hint: "Version Resolver groups related documents and selects the version valid at the requested date."
  },
  report_studio: {
    questions: [],
    parameters: {formats: ["md", "txt", "pdf", "docx", "odt"], include_coverage: true, language: "en", template: "default"},
    hint: "Artifact Studio expects one verified NemoFold analysis JSON as its input and renders five consistent formats."
  },
  platform_proof: {
    questions: ["What is supported by the approved documents?"],
    parameters: {analysis_mode: "local_extractive", evidence_level: "offline", runtime: "offline", network_gate: "closed", max_chunks: 256, formats: ["md"]},
    hint: "Platform Proof produces offline evidence now; live Nebius and Nemotron proof remains false until a separately approved runtime call succeeds."
  },
  storage_policy: {
    questions: [],
    parameters: {allowed_extensions: [".txt", ".md"], naming_template: "{stem}{suffix}", original_policy: "move", retention_action: "keep"},
    hint: "Storage Policies require exactly one approved target root. Dry-run previews every planned action before anything can move."
  },
  smart_inbox: {
    questions: [],
    parameters: {classification_policy: "suffix_routes", routes: [{suffixes: [".txt", ".md"], target_root: 0}], allowed_extensions: [".txt", ".md"], original_policy: "move"},
    hint: "Smart Inbox requires at least one approved target root and routes the full batch only after collision and policy preflight."
  }
};

function newRunId() {
  const now = new Date();
  const timestamp = now.toISOString().replace(/[-:.TZ]/g, "").slice(0, 17);
  const suffix = globalThis.crypto?.randomUUID?.().slice(0, 6) || String(now.getTime()).slice(-6);
  return `web_${timestamp}_${suffix}`;
}

function assignRunId() {
  const custom = $("customRunId").checked;
  const value = custom ? $("runId").value.trim() : newRunId();
  if (!value) throw new Error("Enter a custom Run ID or switch back to automatic IDs.");
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("Run IDs may contain only letters, numbers, underscores and hyphens.");
  $("runId").value = value;
  $("runIdState").textContent = `Assigned to this request: ${value}`;
  return value;
}

function applyAnalysisScale() {
  const selected = analysisScaleDefaults[$("analysisScale").value];
  if (!selected) return;
  try {
    const parameters = JSON.parse($("parameters").value || "{}");
    if ($("workflow").value === "evidence_analyst" || $("workflow").value === "platform_proof") {
      parameters.max_chunks = selected.maxChunks;
      $("parameters").value = JSON.stringify(parameters, null, 2);
    }
    $("providerTokens").value = String(selected.outputTokens);
    $("providerTimeout").value = String(selected.timeoutSeconds);
  } catch {
    $("analysisScale").value = "custom";
  }
}

function providerExecutionSelected() {
  return providerSurfaceEnabled && $("executionMode").value === "provider";
}

function selectedProvider() {
  return providerContracts.get($("providerId").value);
}

function jobPayload() {
  const model = $("modelId").value.trim();
  const payload = {
    schema: "nemofold.job.v1",
    workflow: $("workflow").value,
    input_roots: lines($("inputRoots").value),
    target_roots: lines($("targetRoots").value),
    output_dir: $("outputDir").value.trim(),
    questions: lines($("questions").value),
    privacy_mode: $("privacy").value,
    action_mode: $("actionMode").value,
    model_budget_usd: Number($("budget").value || 0),
    parameters: JSON.parse($("parameters").value || "{}")
  };
  if (model && !providerExecutionSelected()) payload.model_id = model;
  return payload;
}

function providerPayload() {
  return {
    provider_id: $("providerId").value,
    model: $("providerModel").value.trim(),
    max_output_tokens: Number($("providerTokens").value),
    timeout_seconds: Number($("providerTimeout").value)
  };
}

function applyPreparedProvider(provider) {
  if (!provider) {
    $("executionMode").value = "local-core";
    $("externalApproval").checked = false;
    updateProviderPanel();
    return {active: false, reason: null};
  }
  const descriptor = providerContracts.get(provider.provider_id);
  const allowed = descriptor && (!descriptor.external_transfer || externalModelsAllowed);
  $("providerId").value = provider.provider_id;
  $("providerModel").value = provider.model;
  $("providerTokens").value = String(provider.max_output_tokens);
  $("providerTimeout").value = String(provider.timeout_seconds);
  $("executionMode").value = allowed ? "provider" : "local-core";
  $("externalApproval").checked = false;
  updateProviderPanel();
  return {
    active: Boolean(allowed),
    reason: descriptor
      ? "The saved external provider is visible, but this server was not started with the external-model gate."
      : "The saved provider is unavailable in this runtime."
  };
}

function storedList(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function writeStoredList(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value.slice(0, 100)));
    return true;
  } catch {
    $("promptHistoryState").textContent = "Browser storage unavailable; current editor still works.";
    return false;
  }
}

function rememberPromptHistory(runId) {
  const items = lines($("questions").value);
  if (!items.length) return;
  const history = storedList(promptHistoryKey).filter((entry) =>
    JSON.stringify(entry.items) !== JSON.stringify(items)
  );
  history.unshift({
    id: `history-${Date.now()}`,
    name: `${$("workflow").selectedOptions[0]?.textContent || $("workflow").value} · ${runId}`,
    items,
    saved_at: new Date().toISOString()
  });
  writeStoredList(promptHistoryKey, history);
}

function saveCurrentPromptSet() {
  const items = lines($("questions").value);
  if (!items.length) {
    $("promptHistoryState").textContent = "Add at least one question or prompt first.";
    return;
  }
  const suggested = `${$("workflow").selectedOptions[0]?.textContent || "NemoFold"} set`;
  const name = globalThis.prompt("Name this reusable question/prompt set:", suggested)?.trim();
  if (!name) return;
  const catalog = storedList(promptCatalogKey);
  catalog.unshift({id: `saved-${Date.now()}`, name, items, saved_at: new Date().toISOString()});
  if (writeStoredList(promptCatalogKey, catalog)) {
    $("promptHistoryState").textContent = `Saved “${name}” locally.`;
  }
}

function importPromptSet(items, append) {
  const existing = append ? lines($("questions").value) : [];
  const merged = [...existing];
  for (const item of items) if (!merged.includes(item)) merged.push(item);
  $("questions").value = merged.join("\n");
  $("promptHistoryState").textContent = `${items.length} tasks ${append ? "appended" : "loaded"}.`;
  $("promptLibraryDialog").close();
}

function renderPromptLibrary() {
  $("promptCatalogTab").classList.toggle("secondary", promptLibraryView !== "catalog");
  $("promptHistoryTab").classList.toggle("secondary", promptLibraryView !== "history");
  const list = $("promptLibraryList");
  list.replaceChildren();
  const entries = promptLibraryView === "catalog"
    ? [...builtInPromptCatalog, ...storedList(promptCatalogKey)]
    : storedList(promptHistoryKey);
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.textContent = promptLibraryView === "history"
      ? "No previous question or prompt set has been run yet."
      : "No saved catalog entries.";
    list.append(empty);
    return;
  }
  for (const entry of entries) {
    if (!entry || !Array.isArray(entry.items)) continue;
    const card = document.createElement("article");
    const heading = document.createElement("h3");
    heading.textContent = String(entry.name || "Untitled set");
    const count = document.createElement("span");
    count.textContent = `${entry.items.length} tasks`;
    const preview = document.createElement("ol");
    for (const value of entry.items) {
      const item = document.createElement("li");
      item.textContent = String(value);
      preview.append(item);
    }
    const actions = document.createElement("div");
    const use = document.createElement("button");
    use.type = "button";
    use.textContent = "Use set";
    use.addEventListener("click", () => importPromptSet(entry.items.map(String), false));
    const append = document.createElement("button");
    append.type = "button";
    append.className = "secondary";
    append.textContent = "Append";
    append.addEventListener("click", () => importPromptSet(entry.items.map(String), true));
    actions.append(use, append);
    card.append(heading, count, preview, actions);
    list.append(card);
  }
}

function openPromptLibrary(view = "catalog") {
  promptLibraryView = view;
  $("promptCatalogTab").classList.toggle("secondary", view !== "catalog");
  $("promptHistoryTab").classList.toggle("secondary", view !== "history");
  renderPromptLibrary();
  $("promptLibraryDialog").showModal();
}

function selectedWorkflowGraph() {
  return workflowGraphs.get($("workflow").value);
}

const voyageScenes = {
  document: {
    className: "document-center",
    kicker: "INSIDE THE NAUTILUS",
    title: "Document Center",
    text: "Your protected home on board: intake, cleanup, local mail cases and controlled drafts remain inspectable before anything moves or leaves the Nautilus.",
    roadmap: "ACTIVE · smart_inbox + storage_policy + cleanup_rules + mail_to_case + controlled_email"
  },
  analysis: {
    className: "analysis-lab",
    kicker: "THE GREAT OBSERVATION WINDOW",
    title: "Analysis Lab",
    text: "Build a traceable bundle, look into the deep corpus with Captain Nemo, and follow every luminous finding back to its exact source.",
    roadmap: "ACTIVE · bundle_export → anonymize → evidence_analyst + UC07 Research Notebook"
  },
  routines: {
    className: "folder-routines",
    kicker: "SONAR AND ECHO ROUTINES",
    title: "Folder Routines",
    text: "Recurring folders return as sonar echoes: detect changes, resolve valid versions and surface contact or responsibility changes without automatic deletion.",
    roadmap: "ACTIVE · folder_digest + version_resolver + contact_monitor"
  },
  artifacts: {
    className: "artifact-library",
    kicker: "THE NAUTILUS LIBRARY",
    title: "Artifact Studio",
    text: "Reports, ledgers and recovered knowledge are cataloged like shells and sea treasures, with a hash check before a finding receives a green state.",
    roadmap: "ACTIVE · report_studio + verified artifact catalog"
  },
  connections: {
    className: "connections-deck",
    kicker: "SURFACE AND HORIZON",
    title: "Connections",
    text: "The Nautilus has surfaced. Local, provider, Nebius and NemoClaw connections remain separate signals; distant readiness is never presented as proof.",
    roadmap: "STATUS ONLY · platform_proof"
  }
};

function updateVoyageScene(area = null) {
  const workflow = $("workflow").value;
  const key = area || (
    ["smart_inbox", "storage_policy", "cleanup_rules", "mail_to_case", "controlled_email"].includes(workflow) ? "document"
      : ["bundle_export", "evidence_analyst"].includes(workflow) ? "analysis"
        : ["folder_digest", "version_resolver", "contact_monitor"].includes(workflow) ? "routines"
          : workflow === "report_studio" ? "artifacts" : "connections"
  );
  const scene = voyageScenes[key];
  const container = $("voyageScene");
  container.className = `voyage-scene ${scene.className}`;
  $("voyageSceneKicker").textContent = scene.kicker;
  $("voyageSceneTitle").textContent = scene.title;
  $("voyageSceneText").textContent = scene.text;
  $("voyageRoadmap").textContent = scene.roadmap;
  const notebookVisible = key === "analysis" && $("workflow").value === "evidence_analyst";
  $("researchNotebook").hidden = !notebookVisible;
  if (notebookVisible) updateNotebookSnapshot();
}

function setTrafficClip(state, label) {
  $("privacyTraffic").dataset.state = state;
  $("privacySignal").textContent = label;
}

function replacementSummary(counts) {
  const entries = Object.entries(counts || {}).filter(([, count]) => Number(count) > 0);
  return entries.length
    ? entries.map(([category, count]) => `${category} ${count}`).join(" · ")
    : "0 detected";
}

function resetPrivacyCenter() {
  const graph = selectedWorkflowGraph();
  const containsAnonymization = graph?.contains_anonymization === true;
  if (!containsAnonymization) {
    setTrafficClip("neutral", "NOT INCLUDED");
    $("privacyScope").textContent = "This workflow does not prepare an outbound context package.";
    $("privacyReplacements").textContent = "Not required";
    $("privacyMessage").textContent = "No anonymization node is part of the selected workflow contract.";
  } else {
    setTrafficClip("pending", "PREVIEW REQUIRED");
    $("privacyScope").textContent = "Anonymization is part of this workflow.";
    $("privacyReplacements").textContent = "Not checked";
    $("privacyMessage").textContent = "Preview prepares the selected context locally and reports replacement categories without exposing original values.";
  }
  $("privacyTransfer").textContent = "No transfer performed";
}

function updatePrivacyCenter(data, responseOk) {
  const preview = data?.preview;
  const report = data?.report;
  const metadata = report?.metadata || {};
  const anonymization = preview?.anonymization;
  if (anonymization) {
    const passed = responseOk && anonymization.status === "passed";
    setTrafficClip(passed ? "pass" : "fail", passed ? "CHECK PASSED" : "CHECK FAILED");
    $("privacyScope").textContent = passed
      ? `${preview.selected_chunk_count} selected chunks checked locally; source names removed.`
      : "The outbound context did not pass the local privacy check.";
    $("privacyReplacements").textContent = replacementSummary(anonymization.replacement_counts);
    $("privacyTransfer").textContent = preview.transfer_performed
      ? "Transfer recorded"
      : "Preview only · no transfer";
    $("privacyMessage").textContent = passed
      ? `Raw reverse mapping stored: ${String(anonymization.raw_mapping_stored)}. External transfer ready: ${String(preview.external_transfer_ready)}.`
      : "Inspect the returned rejection before any provider run.";
    return;
  }
  if (metadata.anonymization_status) {
    const passed = responseOk && metadata.anonymization_status === "passed";
    setTrafficClip(passed ? "pass" : "fail", passed ? "CHECK PASSED" : "CHECK FAILED");
    $("privacyScope").textContent = passed
      ? "The transmitted context passed local pseudonymization and residual-category checks."
      : "Context preparation or anonymization did not complete.";
    $("privacyReplacements").textContent = replacementSummary(metadata.pseudonymization_counts);
    $("privacyTransfer").textContent = metadata.transfer_performed === true
      ? "Transfer recorded: true"
      : metadata.transfer_performed === false ? "Transfer recorded: false" : "Transfer outcome unknown";
    $("privacyMessage").textContent = `Raw reverse mapping stored: ${String(metadata.raw_mapping_stored === true)}.`;
    return;
  }
  if (!responseOk && selectedWorkflowGraph()?.contains_anonymization === true) {
    setTrafficClip("fail", "CHECK FAILED");
    $("privacyScope").textContent = "The selected job was rejected before a privacy receipt was produced.";
    $("privacyReplacements").textContent = "Unavailable";
    $("privacyTransfer").textContent = "No confirmed transfer";
    $("privacyMessage").textContent = typeof data?.detail === "string" ? data.detail : "Inspect the run dossier for the blocking reason.";
    return;
  }
  const transfer = metadata.transfer_performed;
  if (report && transfer !== true) {
    setTrafficClip("neutral", "NO OUTBOUND TRANSFER");
    $("privacyTransfer").textContent = "Transfer recorded: false";
    $("privacyMessage").textContent = "This run produced no provider privacy receipt because no outbound provider context was used.";
  }
}

function renderWorkflowMap() {
  const graph = selectedWorkflowGraph();
  const map = $("workflowMap");
  map.replaceChildren();
  if (!graph) {
    $("workflowMapTitle").textContent = $("workflow").value;
    $("workflowHint").textContent = workflowDefaults[$("workflow").value]?.hint || "Workflow definition unavailable.";
    $("workflowPrivacyBadge").textContent = "Anonymization state unknown";
    resetPrivacyCenter();
    return;
  }
  $("workflowMapTitle").textContent = $("workflow").selectedOptions[0]?.textContent || graph.workflow;
  $("workflowHint").textContent = graph.description;
  $("workflowPrivacyBadge").textContent = graph.contains_anonymization
    ? "Anonymization included"
    : "No anonymization node";
  $("workflowPrivacyBadge").classList.toggle("included", graph.contains_anonymization);
  graph.nodes.forEach((node, index) => {
    if (index > 0) {
      const edge = document.createElement("span");
      edge.className = "workflow-edge";
      edge.setAttribute("aria-hidden", "true");
      edge.textContent = "→";
      map.append(edge);
    }
    const item = document.createElement("article");
    item.className = `workflow-node ${node.kind}`;
    item.setAttribute("role", "listitem");
    const number = document.createElement("span");
    number.textContent = String(index + 1).padStart(2, "0");
    const label = document.createElement("b");
    label.textContent = node.label;
    const detail = document.createElement("small");
    detail.textContent = node.detail;
    item.append(number, label, detail);
    map.append(item);
  });
  resetPrivacyCenter();
}

function showLocalProviderState(message) {
  $("providerRoute").textContent = "LOCAL CORE";
  $("providerTransport").textContent = message;
  $("externalApprovalRow").hidden = true;
  $("externalApproval").checked = false;
  $("runButton").textContent = publicDemo ? "Run synthetic demo" : "Run locally";
  $("providerHint").textContent = publicDemo
    ? "The public demo is synthetic and ephemeral. Start the loopback-only local app to use Ollama, Codex, or Claude."
    : "Use Preview first to inspect the exact source scope. Provider runtime health is established only by a real bounded run.";
}

function updateProviderPanel({resetModel = false} = {}) {
  const enabled = providerExecutionSelected();
  const descriptor = selectedProvider();
  $("providerId").disabled = !enabled;
  for (const id of ["providerModel", "providerTokens", "providerTimeout"]) {
    $(id).disabled = !enabled || !descriptor;
  }
  $("modelId").disabled = enabled || publicDemo;
  if (!enabled || !descriptor) {
    const workflowMessage = $("workflow").value !== "evidence_analyst"
      ? "This workflow is a local deterministic chain. Choose Evidence Analyst for Codex, Claude or another reasoning worker."
      : "No model transfer. Deterministic NemoFold workflow.";
    showLocalProviderState(
      publicDemo
        ? "Public demo: synthetic, ephemeral, and provider-disabled."
        : workflowMessage
    );
    return;
  }
  if (resetModel || previousProviderId !== descriptor.provider_id) {
    $("providerModel").value = providerModelDefaults[descriptor.provider_id] || "";
    previousProviderId = descriptor.provider_id;
    $("externalApproval").checked = false;
  }
  const external = descriptor.external_transfer === true;
  $("providerRoute").textContent = external ? "EXTERNAL WORKER" : "LOOPBACK WORKER";
  const endpoint = descriptor.default_base_url ? ` · ${descriptor.default_base_url}` : "";
  $("providerTransport").textContent = external
    ? `${descriptor.label} · selected pseudonymized chunks only · competition proof remains false`
    : `${descriptor.label} · ${descriptor.transport}${endpoint} · no external transfer`;
  $("externalApprovalRow").hidden = !external;
  $("externalApproval").disabled = !external;
  $("runButton").textContent = `Analyze with ${descriptor.label}`;
  $("providerHint").textContent = external
    ? "External runs require privacy mode allow_once and the one-run transfer checkbox. No ambient folder authority is transferred."
    : "The local provider must be running on its loopback endpoint. Privacy mode must remain local_only.";
}

function configureProviders(status) {
  publicDemo = status.public_demo === true;
  providerSurfaceEnabled = status.provider_surface_enabled === true;
  externalModelsAllowed = status.external_models_allowed === true;
  providerContracts = new Map(
    (Array.isArray(status.providers) ? status.providers : []).map((item) => [item.provider_id, item])
  );
  const select = $("providerId");
  select.replaceChildren();
  for (const descriptor of providerContracts.values()) {
    const option = document.createElement("option");
    option.value = descriptor.provider_id;
    option.textContent = descriptor.external_transfer && !externalModelsAllowed
      ? `${descriptor.label} — server gate closed`
      : descriptor.label;
    option.disabled = descriptor.external_transfer && !externalModelsAllowed;
    select.append(option);
  }
  if (!select.options.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = publicDemo ? "Unavailable in public demo" : "No provider contracts available";
    select.append(option);
  }
  updateProviderAvailability();
  updateProviderPanel({resetModel: true});
}

function updateProviderAvailability() {
  const providerMode = $("executionMode").querySelector('option[value="provider"]');
  providerMode.disabled = !providerSurfaceEnabled
    || !providerContracts.size
    || $("workflow").value !== "evidence_analyst";
  if (providerMode.disabled && $("executionMode").value === "provider") {
    $("executionMode").value = "local-core";
  }
}

function applyWorkflowDefaults() {
  const defaults = workflowDefaults[$("workflow").value];
  $("questions").value = defaults.questions.join("\n");
  $("parameters").value = JSON.stringify(defaults.parameters, null, 2);
  $("analysisScale").disabled = !["evidence_analyst", "platform_proof"].includes($("workflow").value);
  if (!$("analysisScale").disabled) applyAnalysisScale();
  updateVoyageScene();
  renderWorkflowMap();
  updateProviderAvailability();
  updateProviderPanel();
}

async function execute(endpoint) {
  if (activeRequest) return;
  activeRequest = true;
  const buttons = [...document.querySelectorAll("button")];
  const buttonStates = buttons.map((button) => button.disabled);
  buttons.forEach((button) => { button.disabled = true; });
  const result = $("result");
  result.className = "result";
  const providerMode = providerExecutionSelected();
  const providerAnalysis = endpoint === "run" && providerMode;
  let progressTimer = null;
  try {
    const request = {job: jobPayload()};
    if (!publicDemo) request.run_id = assignRunId();
    if (request.run_id) rememberPromptHistory(request.run_id);
    let apiEndpoint = endpoint;
    let workerLabel = "NemoFold local core";
    if (providerMode) {
      const descriptor = selectedProvider();
      if (!descriptor) throw new Error("Select a provider contract.");
      if (!$("providerModel").value.trim()) throw new Error("Enter the provider model.");
      if (providerAnalysis && descriptor.external_transfer && $("privacy").value !== "allow_once") {
        throw new Error("External providers require Privacy = allow_once.");
      }
      if (!descriptor.external_transfer && $("privacy").value !== "local_only") {
        throw new Error("Local providers require Privacy = local_only.");
      }
      if (providerAnalysis && descriptor.external_transfer && !$("externalApproval").checked) {
        throw new Error("Approve this external transfer once before running.");
      }
      request.provider = providerPayload();
      workerLabel = descriptor.label;
      if (providerAnalysis) {
        request.approve_external_transfer = $("externalApproval").checked;
        apiEndpoint = "provider-analyze";
      } else {
        apiEndpoint = "provider-preview";
      }
    }
    const startedAt = Date.now();
    const progress = document.createElement("div");
    progress.className = "run-progress";
    const progressState = document.createElement("b");
    const progressDetail = document.createElement("span");
    progressState.textContent = providerMode
      ? `${workerLabel} is ${providerAnalysis ? "working" : "being preflighted"}…`
      : endpoint === "preview" ? "NemoFold is building the preview…" : "NemoFold is running locally…";
    const updateElapsed = () => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      progressDetail.textContent = `Run ${request.run_id || "ephemeral demo"} · ${elapsed}s elapsed · request still active`;
    };
    updateElapsed();
    progressTimer = globalThis.setInterval(updateElapsed, 1000);
    progress.append(progressState, progressDetail);
    result.replaceChildren(progress);
    const response = await fetch(`/api/${apiEndpoint}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(request)
    });
    const data = await response.json();
    updatePrivacyCenter(data, response.ok);
    result.classList.toggle("error", !response.ok);
    const summary = document.createElement("div");
    summary.className = "result-summary";
    const report = data?.report;
    const errorStatus = typeof data?.error === "string"
      ? data.error
      : typeof data?.detail === "string" ? data.detail : "rejected";
    const preview = data?.preview;
    const cloudProof = data?.cloud_proof ?? report?.metadata?.cloud_proof ?? preview?.cloud_proof;
    const provider = report?.metadata?.provider ?? preview?.provider;
    const transfer = report?.metadata?.transfer_performed ?? preview?.transfer_performed;
    const facts = [
      ["REQUEST", response.ok ? "accepted" : `HTTP ${response.status}`],
      ["RUN ID", report?.run_id || request.run_id || "ephemeral"],
      ["WORKFLOW", report?.workflow || request.job.workflow],
      ["STATUS", response.ok ? report?.status || "returned" : errorStatus],
      ...(provider ? [["PROVIDER", `${provider.provider_id} / ${provider.model}`]] : []),
      ...(transfer !== undefined ? [["TRANSFER", String(transfer)]] : []),
      ["CLOUD PROOF", cloudProof === true ? "true" : cloudProof === false ? "false" : "not claimed"]
    ];
    for (const [name, value] of facts) {
      const fact = document.createElement("span");
      const label = document.createElement("b");
      label.textContent = name;
      fact.append(label, document.createTextNode(`: ${String(value)}`));
      summary.append(fact);
    }
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(data, null, 2);
    result.replaceChildren(summary, pre);
    if (!publicDemo) {
      const finalStatus = report?.status || (response.ok ? "completed" : "rejected");
      $("runIdState").textContent = `Last request ${report?.run_id || request.run_id}: ${finalStatus}. A new automatic ID will be used next time.`;
      if (endpoint === "run") $("externalApproval").checked = false;
      if (artifactSurfaceEnabled) await loadArtifacts();
      if (endpoint === "run" && report?.run_id) await linkResearchRun(report.run_id);
    }
  } catch (error) {
    result.className = "result error";
    const message = error instanceof Error ? error.message : String(error);
    result.textContent = message;
    updatePrivacyCenter({detail: message}, false);
  } finally {
    if (progressTimer !== null) globalThis.clearInterval(progressTimer);
    activeRequest = false;
    buttons.forEach((button, index) => { button.disabled = buttonStates[index]; });
  }
}

async function loadFolderChoices(path = null) {
  $("folderStatus").textContent = "Loading approved folders…";
  const response = await fetch("/api/folders", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({path})
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || data.error || "Folder request failed.");
  folderCurrentPath = data.current?.path || null;
  $("folderCurrent").textContent = folderCurrentPath || "Choose one server-approved root.";
  $("folderUp").disabled = !data.parent;
  $("folderUp").dataset.path = data.parent || "";
  $("folderSelectCurrent").disabled = !folderCurrentPath;
  const choices = $("folderChoices");
  choices.replaceChildren();
  const entries = folderCurrentPath ? data.directories : data.roots;
  for (const entry of entries || []) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "folder-choice secondary";
    const name = document.createElement("b");
    name.textContent = entry.name;
    const value = document.createElement("span");
    value.textContent = entry.path;
    button.append(name, value);
    button.addEventListener("click", () => loadFolderChoices(entry.path).catch(showFolderError));
    choices.append(button);
  }
  if (!entries?.length) {
    const empty = document.createElement("p");
    empty.textContent = folderCurrentPath ? "No child folders inside this location." : "No approved roots are available.";
    choices.append(empty);
  }
  const skipped = Number(data.skipped_count || 0);
  $("folderStatus").textContent = skipped
    ? `${skipped} inaccessible or linked folders were omitted.`
    : "Only real folders inside server-approved roots are shown.";
}

function showFolderError(error) {
  $("folderStatus").textContent = error instanceof Error ? error.message : String(error);
}

function openFolderDialog(targetId) {
  if (!folderPickerEnabled) return;
  folderTargetId = targetId;
  $("folderDialogTitle").textContent = targetId === "outputDir" ? "Choose output folder" : "Add a folder";
  $("folderDialog").showModal();
  loadFolderChoices(null).catch(showFolderError);
}

function useCurrentFolder() {
  if (!folderCurrentPath || !folderTargetId) return;
  const target = $(folderTargetId);
  if (folderTargetId === "outputDir") {
    target.value = folderCurrentPath;
  } else {
    const values = lines(target.value);
    if (!values.includes(folderCurrentPath)) values.push(folderCurrentPath);
    target.value = values.join("\n");
  }
  $("folderDialog").close();
  if (folderTargetId === "outputDir" && artifactSurfaceEnabled) loadArtifacts();
}

function artifactViewUrl(outputDir, path) {
  const query = new URLSearchParams({output_dir: outputDir, path});
  return `/api/artifact?${query.toString()}`;
}

function artifactLink(label, outputDir, path) {
  const link = document.createElement("a");
  link.href = artifactViewUrl(outputDir, path);
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = label;
  return link;
}

async function loadArtifacts() {
  const gallery = $("artifactGallery");
  const outputDir = $("outputDir").value.trim();
  $("artifactScope").textContent = outputDir || "No output directory selected";
  if (!artifactSurfaceEnabled || !outputDir) {
    gallery.textContent = publicDemo
      ? "Public demo artifacts are intentionally ephemeral. Use the local console for a persistent studio."
      : "Choose an output directory to inspect its run ledgers.";
    return;
  }
  gallery.textContent = "Verifying run ledgers and artifact hashes…";
  try {
    const response = await fetch("/api/artifacts", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({output_dir: outputDir})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || "Artifact catalog failed.");
    gallery.replaceChildren();
    if (!data.runs?.length) {
      const empty = document.createElement("p");
      empty.textContent = "No run ledgers exist in this output directory yet.";
      gallery.append(empty);
      return;
    }
    for (const run of data.runs) {
      const card = document.createElement("article");
      const status = ["executed", "planned", "blocked", "failed"].includes(run.status) ? run.status : "unknown";
      card.className = `artifact-run ${status}`;
      const head = document.createElement("div");
      const heading = document.createElement("h3");
      heading.textContent = `${run.workflow} · ${run.run_id}`;
      const badge = document.createElement("span");
      badge.textContent = run.verification?.valid
        ? `${String(run.status).toUpperCase()} · LEDGER VERIFIED`
        : `${String(run.status).toUpperCase()} · VERIFICATION FAILED`;
      head.append(heading, badge);
      const proof = document.createElement("p");
      proof.textContent = run.verification?.valid
        ? `${run.verification.checked_artifacts} artifact hashes checked. The ledger contract passed.`
        : `Verification errors: ${(run.verification?.errors || []).join(", ") || "unknown"}`;
      const files = document.createElement("div");
      files.className = "artifact-files";
      files.append(artifactLink("Open evidence ledger", data.output_dir, run.ledger_path));
      for (const artifact of run.artifacts || []) {
        const item = document.createElement("div");
        const description = document.createElement("span");
        description.textContent = `${artifact.format} · ${artifact.name}`;
        item.append(description);
        if (artifact.available) item.append(artifactLink("Open", data.output_dir, artifact.path));
        else {
          const missing = document.createElement("b");
          missing.textContent = "missing";
          item.append(missing);
        }
        files.append(item);
      }
      if (!run.artifacts?.length) {
        const empty = document.createElement("p");
        empty.className = "artifact-empty";
        empty.textContent = run.errors?.length
          ? `No artifacts were created. Blockers: ${run.errors.join(", ")}.`
          : "This run recorded no artifacts.";
        files.append(empty);
      }
      card.append(head, proof, files);
      gallery.append(card);
    }
  } catch (error) {
    gallery.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function loadDraftInbox() {
  const select = $("draftSelect");
  select.replaceChildren();
  if (!draftSurfaceEnabled) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Prepared jobs unavailable on this surface";
    select.append(option);
    $("draftLoad").disabled = true;
    return;
  }
  $("draftState").textContent = "Loading prepared jobs…";
  try {
    const response = await fetch("/api/drafts");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || "Draft inbox failed.");
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = data.drafts?.length ? "Choose a prepared job" : "No prepared jobs waiting";
    select.append(empty);
    for (const draft of data.drafts || []) {
      const option = document.createElement("option");
      option.value = draft.draft_id;
      option.textContent = `${draft.name} · ${draft.workflow} · ${draft.source}`;
      select.append(option);
    }
    $("draftLoad").disabled = true;
    $("draftState").textContent = `${data.drafts?.length || 0} prepared jobs · approvals are never imported.`;
  } catch (error) {
    $("draftState").textContent = error instanceof Error ? error.message : String(error);
  }
}

function applyDraft(draft) {
  const job = draft.job || {};
  if (!workflowDefaults[job.workflow]) throw new Error("Draft workflow is unavailable in this console.");
  $("workflow").value = job.workflow;
  $("inputRoots").value = (job.input_roots || []).join("\n");
  $("targetRoots").value = (job.target_roots || []).join("\n");
  $("outputDir").value = job.output_dir || "";
  $("questions").value = (job.questions || []).join("\n");
  $("privacy").value = job.privacy_mode || "local_only";
  $("actionMode").value = job.action_mode || "dry_run";
  $("modelId").value = job.model_id || "";
  $("budget").value = String(job.model_budget_usd || 0);
  $("parameters").value = JSON.stringify(job.parameters || {}, null, 2);
  const chunkCount = Number(job.parameters?.max_chunks);
  const scale = Object.entries(analysisScaleDefaults).find(([, item]) => item.maxChunks === chunkCount);
  $("analysisScale").value = scale?.[0] || "custom";
  updateVoyageScene();
  renderWorkflowMap();
  updateProviderAvailability();
  const provider = draft.provider;
  const providerState = applyPreparedProvider(provider);
  $("draftState").textContent = provider && !providerState.active
    ? `Loaded “${draft.name}” for review. ${providerState.reason} No approval was imported.`
    : `Loaded “${draft.name}” for review. No approval was imported.`;
  if (artifactSurfaceEnabled) loadArtifacts();
}

async function loadSelectedDraft() {
  const id = $("draftSelect").value;
  if (!id) return;
  $("draftState").textContent = "Loading draft contract…";
  try {
    const response = await fetch(`/api/draft?id=${encodeURIComponent(id)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || "Draft load failed.");
    applyDraft(data.draft);
  } catch (error) {
    $("draftState").textContent = error instanceof Error ? error.message : String(error);
  }
}

function updateNotebookSnapshot() {
  const sourceCount = lines($("inputRoots").value).length;
  const questionCount = lines($("questions").value).length;
  $("notebookSourceCount").textContent = `${sourceCount} approved root${sourceCount === 1 ? "" : "s"}`;
  $("notebookQuestionCount").textContent = `${questionCount} question${questionCount === 1 ? "" : "s"} or prompt${questionCount === 1 ? "" : "s"}`;
}

function renderNotebookRuns(notebook) {
  const runs = $("notebookRuns");
  runs.replaceChildren();
  const entries = Array.isArray(notebook?.runs) ? notebook.runs : [];
  $("notebookRunCount").textContent = `${entries.length} linked ledger${entries.length === 1 ? "" : "s"}`;
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.textContent = "No verified runs linked yet. The next completed run can join this investigation automatically.";
    runs.append(empty);
    return;
  }
  for (const run of entries) {
    const row = document.createElement("div");
    row.className = `notebook-run ${run.verification?.valid ? "valid" : "invalid"}`;
    const title = document.createElement("b");
    title.textContent = `${run.workflow || "run"} · ${run.run_id}`;
    const state = document.createElement("span");
    state.textContent = `${run.status || "unknown"} · ${run.verification?.checked_artifacts || 0} hashes checked`;
    const proof = document.createElement("i");
    proof.textContent = run.verification?.valid ? "LEDGER VERIFIED" : "VERIFY FAILED";
    if (artifactSurfaceEnabled && notebook?.job?.output_dir && run.ledger_path) {
      const link = artifactLink("Open ledger", notebook.job.output_dir, run.ledger_path);
      link.append(document.createTextNode(" · "));
      link.append(proof);
      row.append(title, state, link);
    } else {
      row.append(title, state, proof);
    }
    runs.append(row);
  }
}

function applyResearchNotebook(notebook) {
  const job = notebook.job || {};
  if (job.workflow !== "evidence_analyst") throw new Error("Research Notebook requires Evidence Analyst.");
  currentNotebookId = notebook.notebook_id;
  $("notebookName").value = notebook.name || "";
  $("notebookGoal").value = notebook.goal || "";
  $("workflow").value = "evidence_analyst";
  $("inputRoots").value = (job.input_roots || []).join("\n");
  $("targetRoots").value = "";
  $("outputDir").value = job.output_dir || "";
  $("questions").value = (job.questions || []).join("\n");
  $("privacy").value = job.privacy_mode || "local_only";
  $("actionMode").value = "dry_run";
  $("modelId").value = job.model_id || "";
  $("budget").value = String(job.model_budget_usd || 0);
  $("parameters").value = JSON.stringify(job.parameters || {}, null, 2);
  const chunkCount = Number(job.parameters?.max_chunks);
  const scale = Object.entries(analysisScaleDefaults).find(([, item]) => item.maxChunks === chunkCount);
  $("analysisScale").value = scale?.[0] || "custom";
  updateVoyageScene("analysis");
  renderWorkflowMap();
  updateProviderAvailability();
  const provider = notebook.provider;
  const providerState = applyPreparedProvider(provider);
  updateNotebookSnapshot();
  renderNotebookRuns(notebook);
  $("notebookState").textContent = provider && !providerState.active
    ? `Loaded “${notebook.name}”. ${providerState.reason} External-transfer approval remains off.`
    : `Loaded “${notebook.name}”. External-transfer approval remains off.`;
  if (artifactSurfaceEnabled) loadArtifacts();
}

async function loadResearchNotebooks() {
  const select = $("notebookSelect");
  select.replaceChildren();
  if (!notebookSurfaceEnabled) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Research notebooks unavailable on this surface";
    select.append(option);
    $("notebookLoad").disabled = true;
    $("notebookSave").disabled = true;
    return;
  }
  try {
    const response = await fetch("/api/notebooks");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || "Research notebook list failed.");
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = data.notebooks?.length ? "Choose a saved investigation" : "No saved investigations yet";
    select.append(empty);
    for (const notebook of data.notebooks || []) {
      const option = document.createElement("option");
      option.value = notebook.notebook_id;
      option.textContent = `${notebook.name} · ${notebook.question_count} tasks · ${notebook.run_count} runs`;
      select.append(option);
    }
    if (currentNotebookId && [...select.options].some((option) => option.value === currentNotebookId)) {
      select.value = currentNotebookId;
    }
    $("notebookLoad").disabled = !select.value;
    $("notebookSave").disabled = false;
    $("notebookState").textContent = `${data.notebooks?.length || 0} local investigations available. Approvals and API keys are never stored.`;
  } catch (error) {
    $("notebookState").textContent = error instanceof Error ? error.message : String(error);
  }
}

async function loadSelectedNotebook() {
  const id = $("notebookSelect").value;
  if (!id) return;
  $("notebookState").textContent = "Loading investigation…";
  try {
    const response = await fetch(`/api/notebook?id=${encodeURIComponent(id)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || "Research notebook load failed.");
    applyResearchNotebook(data.notebook);
  } catch (error) {
    $("notebookState").textContent = error instanceof Error ? error.message : String(error);
  }
}

function newResearchNotebook() {
  currentNotebookId = null;
  $("notebookSelect").value = "";
  $("notebookName").value = "";
  $("notebookGoal").value = "";
  $("notebookRunCount").textContent = "0 linked ledgers";
  renderNotebookRuns({runs: []});
  updateNotebookSnapshot();
  $("notebookState").textContent = "New investigation: the current Evidence Analyst scope and tasks will be captured when you save.";
}

async function saveResearchNotebook() {
  if (!notebookSurfaceEnabled) return;
  try {
    if ($("workflow").value !== "evidence_analyst") throw new Error("Select Evidence Analyst before saving an investigation.");
    const name = $("notebookName").value.trim();
    if (!name) throw new Error("Name the investigation before saving it.");
    const payload = {
      name,
      goal: $("notebookGoal").value.trim(),
      job: jobPayload(),
      provider: providerExecutionSelected() ? providerPayload() : null
    };
    if (currentNotebookId) payload.notebook_id = currentNotebookId;
    $("notebookState").textContent = "Saving the local investigation snapshot…";
    const response = await fetch("/api/notebooks", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || "Research notebook save failed.");
    currentNotebookId = data.notebook.notebook_id;
    applyResearchNotebook(data.notebook);
    await loadResearchNotebooks();
    $("notebookState").textContent = `Saved “${data.notebook.name}” locally. The next completed ledger will be linked.`;
  } catch (error) {
    $("notebookState").textContent = error instanceof Error ? error.message : String(error);
  }
}

async function linkResearchRun(runId) {
  if (!notebookSurfaceEnabled || !currentNotebookId || !runId) return;
  try {
    const response = await fetch("/api/notebook-run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({notebook_id: currentNotebookId, run_id: runId})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || "Run could not be linked.");
    renderNotebookRuns(data.notebook);
    $("notebookState").textContent = `Run ${runId} linked to “${data.notebook.name}”; ledger verification is shown below.`;
    await loadResearchNotebooks();
  } catch (error) {
    $("notebookState").textContent = `Investigation saved, but run link failed: ${error instanceof Error ? error.message : String(error)}`;
  }
}

async function loadStatus() {
  try {
    const response = await fetch("/api/status");
    const status = await response.json();
    workflowGraphs = new Map(
      (Array.isArray(status.workflow_graphs) ? status.workflow_graphs : []).map((item) => [item.workflow, item])
    );
    folderPickerEnabled = status.folder_picker_enabled === true;
    artifactSurfaceEnabled = status.artifact_surface_enabled === true;
    draftSurfaceEnabled = status.draft_surface_enabled === true;
    notebookSurfaceEnabled = status.notebook_surface_enabled === true;
    configureProviders(status);
    if (publicDemo) {
      const supported = new Set(status.workflows);
      for (const option of [...$("workflow").options]) {
        if (!supported.has(option.value)) option.remove();
      }
      $("inputRoots").value = "demo://synthetic-home";
      $("targetRoots").value = "";
      $("outputDir").value = "demo://ephemeral";
      $("privacy").value = "local_only";
      $("actionMode").value = "dry_run";
      $("modelId").value = "";
      $("budget").value = "0";
      for (const id of ["inputRoots", "targetRoots", "outputDir", "modelId", "budget", "parameters"]) {
        $(id).readOnly = true;
      }
      $("privacy").disabled = true;
      $("actionMode").disabled = true;
      applyWorkflowDefaults();
      updateProviderPanel();
      for (const button of document.querySelectorAll("[data-folder-target]")) button.disabled = true;
    } else {
      applyWorkflowDefaults();
      for (const button of document.querySelectorAll("[data-folder-target]")) {
        button.disabled = !folderPickerEnabled;
      }
    }
    await loadDraftInbox();
    await loadResearchNotebooks();
    await loadArtifacts();
    $("systemState").textContent = status.live_runtime_ready
      ? "Live runtime ready"
      : publicDemo ? "Public synthetic demo · read-only" : "Local runtime ready · live proof open";
    $("systemState").classList.add(status.live_runtime_ready ? "ok" : "warn");
    $("cloudBadge").textContent = `Cloud proof: ${status.cloud_proof}`;
  } catch {
    $("systemState").textContent = "Runtime unavailable";
    $("systemState").classList.add("warn");
  }
}

$("runId").value = "";
$("workflow").addEventListener("change", applyWorkflowDefaults);
$("executionMode").addEventListener("change", () => { resetPrivacyCenter(); updateProviderPanel(); });
$("providerId").addEventListener("change", () => { resetPrivacyCenter(); updateProviderPanel({resetModel: true}); });
$("analysisScale").addEventListener("change", applyAnalysisScale);
$("customRunId").addEventListener("change", () => {
  $("runId").disabled = !$("customRunId").checked;
  if (!$("customRunId").checked) $("runId").value = "";
  $("runIdState").textContent = $("customRunId").checked
    ? "Enter one deliberate ID. Reusing it may be rejected as a duplicate."
    : "Automatic mode: a fresh ID is assigned on every request.";
});
$("jobForm").addEventListener("submit", (event) => { event.preventDefault(); execute("run"); });
$("previewButton").addEventListener("click", () => execute("preview"));
for (const button of document.querySelectorAll("[data-folder-target]")) {
  button.addEventListener("click", () => openFolderDialog(button.dataset.folderTarget));
}
$("folderUp").addEventListener("click", () => loadFolderChoices($("folderUp").dataset.path || null).catch(showFolderError));
$("folderSelectCurrent").addEventListener("click", useCurrentFolder);
$("promptLibraryButton").addEventListener("click", () => openPromptLibrary("catalog"));
$("promptSaveButton").addEventListener("click", saveCurrentPromptSet);
$("promptLibraryClose").addEventListener("click", () => $("promptLibraryDialog").close());
$("promptCatalogTab").addEventListener("click", () => { promptLibraryView = "catalog"; renderPromptLibrary(); });
$("promptHistoryTab").addEventListener("click", () => { promptLibraryView = "history"; renderPromptLibrary(); });
$("artifactRefresh").addEventListener("click", loadArtifacts);
$("outputDir").addEventListener("change", loadArtifacts);
$("draftRefresh").addEventListener("click", loadDraftInbox);
$("draftSelect").addEventListener("change", () => { $("draftLoad").disabled = !$("draftSelect").value; });
$("draftLoad").addEventListener("click", loadSelectedDraft);
$("notebookRefresh").addEventListener("click", loadResearchNotebooks);
$("notebookSelect").addEventListener("change", () => { $("notebookLoad").disabled = !$("notebookSelect").value; });
$("notebookLoad").addEventListener("click", loadSelectedNotebook);
$("notebookNew").addEventListener("click", newResearchNotebook);
$("notebookSave").addEventListener("click", saveResearchNotebook);
$("inputRoots").addEventListener("input", updateNotebookSnapshot);
$("questions").addEventListener("input", updateNotebookSnapshot);
for (const button of document.querySelectorAll("[data-workflow-open]")) {
  button.addEventListener("click", () => {
    $("workflow").value = button.dataset.workflowOpen;
    applyWorkflowDefaults();
    $("jobForm").scrollIntoView({behavior: "smooth", block: "start"});
  });
}
for (const button of document.querySelectorAll("[data-artifact-open]")) {
  button.addEventListener("click", () => {
    updateVoyageScene("artifacts");
    $("artifactStudio").scrollIntoView({behavior: "smooth", block: "start"});
    loadArtifacts();
  });
}
loadStatus();
