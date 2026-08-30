const $ = (id) => document.getElementById(id);
const lines = (value) => value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
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
  return `web_${now.toISOString().replace(/[-:.TZ]/g, "").slice(0, 14)}`;
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
  if (model) payload.model_id = model;
  return payload;
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
  result.textContent = endpoint === "preview" ? "Building bounded preview…" : "Running local workflow…";
  try {
    const response = await fetch(`/api/${endpoint}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({run_id: $("runId").value.trim(), job: jobPayload()})
    });
    const data = await response.json();
    result.classList.toggle("error", !response.ok);
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(data, null, 2);
    result.replaceChildren(pre);
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
    $("systemState").textContent = status.live_runtime_ready
      ? "Live runtime ready"
      : "Local runtime ready · live proof open";
    $("systemState").classList.add(status.live_runtime_ready ? "ok" : "warn");
    $("cloudBadge").textContent = `Cloud proof: ${status.cloud_proof}`;
  } catch {
    $("systemState").textContent = "Runtime unavailable";
    $("systemState").classList.add("warn");
  }
}

$("runId").value = newRunId();
$("workflow").addEventListener("change", applyWorkflowDefaults);
$("jobForm").addEventListener("submit", (event) => { event.preventDefault(); execute("run"); });
$("previewButton").addEventListener("click", () => execute("preview"));
loadStatus();
