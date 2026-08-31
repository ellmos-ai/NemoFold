const $ = (id) => document.getElementById(id);
const lines = (value) => value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
let publicDemo = false;
let providerSurfaceEnabled = false;
let externalModelsAllowed = false;
let providerContracts = new Map();
let previousProviderId = "";
const providerModelDefaults = {
  ollama: "qwen3:4b",
  "lm-studio": "local-model",
  "codex-cli": "gpt-5.4",
  "claude-code": "sonnet",
  openai: "",
  anthropic: ""
};
const workflowDefaults = {
  evidence_analyst: {
    questions: ["When does the current policy begin?", "Which earlier wording changed?"],
    parameters: {max_chunks: 8, formats: ["md", "txt"], conflict_scan: true},
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
    parameters: {analysis_mode: "local_extractive", evidence_level: "offline", runtime: "offline", network_gate: "closed", max_chunks: 8, formats: ["md"]},
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
    showLocalProviderState(
      publicDemo
        ? "Public demo: synthetic, ephemeral, and provider-disabled."
        : "No model transfer. Deterministic NemoFold workflow."
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
  const providerMode = $("executionMode").querySelector('option[value="provider"]');
  providerMode.disabled = !providerSurfaceEnabled || !providerContracts.size;
  if (providerMode.disabled) $("executionMode").value = "local-core";
  updateProviderPanel({resetModel: true});
}

function applyWorkflowDefaults() {
  const defaults = workflowDefaults[$("workflow").value];
  $("questions").value = defaults.questions.join("\n");
  $("parameters").value = JSON.stringify(defaults.parameters, null, 2);
  $("workflowHint").textContent = defaults.hint;
}

async function execute(endpoint) {
  const buttons = document.querySelectorAll("button");
  buttons.forEach((button) => { button.disabled = true; });
  const result = $("result");
  result.className = "result";
  const providerAnalysis = endpoint === "run" && providerExecutionSelected();
  result.textContent = endpoint === "preview"
    ? "Building bounded preview…"
    : publicDemo
      ? "Running bounded synthetic demo…"
      : providerAnalysis ? "Preparing bounded provider analysis…" : "Running local workflow…";
  try {
    const request = {job: jobPayload()};
    if (!publicDemo) request.run_id = $("runId").value.trim();
    let apiEndpoint = endpoint;
    if (providerAnalysis) {
      const descriptor = selectedProvider();
      if (!descriptor) throw new Error("Select a provider contract.");
      if (!$("providerModel").value.trim()) throw new Error("Enter the provider model.");
      if (descriptor.external_transfer && $("privacy").value !== "allow_once") {
        throw new Error("External providers require Privacy = allow_once.");
      }
      if (!descriptor.external_transfer && $("privacy").value !== "local_only") {
        throw new Error("Local providers require Privacy = local_only.");
      }
      if (descriptor.external_transfer && !$("externalApproval").checked) {
        throw new Error("Approve this external transfer once before running.");
      }
      request.provider = providerPayload();
      request.approve_external_transfer = $("externalApproval").checked;
      apiEndpoint = "provider-analyze";
    }
    const response = await fetch(`/api/${apiEndpoint}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(request)
    });
    const data = await response.json();
    result.classList.toggle("error", !response.ok);
    const summary = document.createElement("div");
    summary.className = "result-summary";
    const report = data?.report;
    const errorStatus = typeof data?.error === "string"
      ? data.error
      : typeof data?.detail === "string" ? data.detail : "rejected";
    const cloudProof = data?.cloud_proof ?? report?.metadata?.cloud_proof;
    const provider = report?.metadata?.provider;
    const transfer = report?.metadata?.transfer_performed;
    const facts = [
      ["REQUEST", response.ok ? "accepted" : `HTTP ${response.status}`],
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
    if (response.ok && endpoint === "run" && !publicDemo) {
      $("runId").value = newRunId();
      $("externalApproval").checked = false;
    }
  } catch (error) {
    result.className = "result error";
    result.textContent = error instanceof Error ? error.message : String(error);
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

async function loadStatus() {
  try {
    const response = await fetch("/api/status");
    const status = await response.json();
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
    }
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

$("runId").value = newRunId();
$("workflow").addEventListener("change", applyWorkflowDefaults);
$("executionMode").addEventListener("change", () => updateProviderPanel());
$("providerId").addEventListener("change", () => updateProviderPanel({resetModel: true}));
$("jobForm").addEventListener("submit", (event) => { event.preventDefault(); execute("run"); });
$("previewButton").addEventListener("click", () => execute("preview"));
loadStatus();
