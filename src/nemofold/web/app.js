const $ = (id) => document.getElementById(id);
const pageByPath = new Map([
  ["/", "overview"],
  ["/folders", "folders"],
  ["/processes", "processes"],
  ["/governance", "governance"],
  ["/connections", "connections"]
]);
const pageTabs = {
  processes: ["workflows", "registry", "artifacts"],
  governance: ["policies", "rules"]
};
const normalizedPath = globalThis.location.pathname.replace(/\/+$/, "") || "/";
const currentPage = pageByPath.get(normalizedPath) || "overview";
const searchParameters = new URLSearchParams(globalThis.location.search);
const requestedWorkflow = searchParameters.get("workflow");
const availableTabs = pageTabs[currentPage] || [];
const requestedTab = searchParameters.get("tab");
const currentTab = availableTabs.includes(requestedTab) ? requestedTab : (availableTabs[0] || "");
// A room shows the use cases that belong to it. The tag is the binding, so a
// deep link can name one (/processes?tab=workflows&tag=scheduled is where the
// old /routines route lands) and a room can prefer one without hiding the rest.
const roomTag = {folders: "folder-watch"};
let activeTag = searchParameters.get("tag") || roomTag[currentPage] || "";
const tabTitles = {
  workflows: "Workflows — NemoFold",
  registry: "Registry — NemoFold",
  artifacts: "Artifacts — NemoFold",
  policies: "Policies — NemoFold",
  rules: "Rules — NemoFold"
};
const pageConfiguration = {
  overview: {title: "NemoFold — Local evidence workspace", defaultWorkflow: "smart_inbox", workflows: []},
  folders: {title: "Folders — NemoFold", defaultWorkflow: "smart_inbox", workflows: []},
  processes: {title: "Processes & Workflows — NemoFold", defaultWorkflow: "evidence_analyst", workflows: []},
  governance: {title: "Governance — NemoFold", defaultWorkflow: "storage_policy", workflows: []},
  connections: {title: "Connections — NemoFold", defaultWorkflow: "platform_proof", workflows: []}
};
document.body.dataset.page = currentPage;
document.body.dataset.tab = currentTab;
document.title = tabTitles[currentTab] || pageConfiguration[currentPage].title;
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
let voyageSurfaceEnabled = false;
let policySurfaceEnabled = false;
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
  daily_arrivals: {
    questions: [],
    parameters: {summary_length: 3, export_task_snippet: true, task_run_at: "07:00:00", formats: ["md"]},
    hint: "Daily Arrivals compares the folder against a snapshot you name and reports each new file with size, time and a short content. The owner is named where the platform can, and the reason is named where it cannot. The exported task file is yours to install; NemoFold registers nothing."
  },
  synopsis_merge: {
    questions: [],
    parameters: {application_domain: "general_documents", formats: ["md", "pdf"]},
    hint: "Synopsis Merge folds several documents into one synopsis. Every paragraph keeps its source and line, and where two sources answer the same label differently both readings stay in a conflict block."
  },
  fact_distill: {
    questions: [],
    parameters: {dedupe_scope: "normalized", formats: ["md", "pdf"], focus_terms: []},
    hint: "Fact Distill lifts quotable sentences from every approved source and strikes repeated statements from the findings. Every struck occurrence stays visible in its own appendix with the statement it repeats."
  },
  document_registry: {
    questions: [],
    parameters: {column_template: "medical_reports", formats: ["md", "pdf"], topic_filter: []},
    hint: "Document Registry extracts the columns you declare from every approved document into one table. Each filled cell keeps its source and line; a cell the sources do not answer stays empty."
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
  person_registry: {
    questions: [],
    parameters: {formats: ["md"], match_surnames: false},
    hint: "Person Registry lists the people your documents declare under named fields, never a name a heuristic thought it saw. It writes an identified form, a pseudonymous form that may travel, and a local identity map that must not."
  },
  relation_model: {
    questions: [],
    parameters: {formats: ["md"], pseudonymous: false},
    hint: "Relation Model draws an edge only where a sentence states one. Being named in the same sentence is shown as exactly that, and every edge carries the sentence it came from."
  },
  person_timeline: {
    questions: [],
    parameters: {formats: ["md"]},
    hint: "Person Timeline puts every stated time on a lane. A time the sources leave open stays undetermined and is drawn as a band, never as a point that would look like a fact."
  },
  coverage_timeline: {
    questions: [],
    parameters: {formats: ["md"], start_field: "Deckung ab", end_field: "Deckung bis", label_field: "Tarif"},
    hint: "Coverage Timeline reads declared contract fields to show when somebody was covered under which tariff. A contract without an end date is drawn with an open end."
  },
  cost_timeline: {
    questions: [],
    parameters: {formats: ["md"], contract_field: "Vertrag", amount_field: "Betrag", cadence_field: "Turnus", due_date_field: "Nächste Fälligkeit"},
    hint: "Cost Timeline plans recurring and irregular costs from declared contract fields, keeping unknown due dates separate rather than guessing exact moments."
  },
  subscription_reconcile: {
    questions: [],
    parameters: {formats: ["md"], min_subscriptions: 1, require_unambiguous_matches: true},
    hint: "Subscription Reconciliation reconciles declared subscriptions with incoming message/invoice evidence, identifying price discrepancies and status mismatches."
  },
  medication_reconcile: {
    questions: [],
    parameters: {formats: ["md"], min_medications: 1, require_unambiguous_dosages: true, application_domain: "medical_reports"},
    hint: "Medication Reconciliation consolidates medication plans across medical reports, identifying conflicting dosages and duplicate active ingredients without medical overreach."
  },
  database_reader: {
    questions: [],
    parameters: {formats: ["md"], min_records: 1, require_read_only: true},
    hint: "Database Reader safely reads approved specialist SQLite databases (HausLagerist, MediPlaner) under strict read-only and schema protection."
  },
  knowledge_composer: {
    questions: [],
    parameters: {formats: ["md", "json"], profile: "cv_ascii", min_knowledge_items: 1},
    hint: "Knowledge Composer generates grounded documents (ASCII CVs, autism worksheets, counseling worksheets) strictly from verified local knowledge bases."
  },
  alibi_weave: {
    questions: [],
    parameters: {formats: ["md"], places: [], tolerance_minutes: 90},
    hint: "Alibi Weave keeps a self-report on one line and a confirmation from another source on a second. Name the places to compare; without them nothing is confirmed by time alone."
  },
  contradiction_synopsis: {
    questions: [],
    parameters: {formats: ["md"], contested_terms: []},
    hint: "Contradiction Synopsis puts disagreeing statements side by side in both wordings with their anchors. It names which sources disagree; it never decides which is right."
  },
  corpus_query: {
    questions: ["Wo taucht ein blauer VW Golf auf?"],
    parameters: {formats: ["md"], terms: [], partition_size: 20, dedupe_scope: "normalized"},
    hint: "Corpus Query answers one narrow question over a large bundle through staged aggregation. Every match is a quoted sentence with its sources; no match means the corpus does not contain one."
  },
  web_research: {
    questions: [],
    parameters: {formats: ["md"], queries: [], max_results: 5},
    hint: "Web Research searches the open web behind four gates that all have to hold: this server allows it, you approve the call, the adapter has its key, and no query carries private content. Every result keeps the address it came from."
  },
  dossier: {
    questions: [],
    parameters: {formats: ["md"], queries: [], subject: "", max_results: 5},
    hint: "Dossier collects cited search results on a subject you name into a reading list. It is not a finding about anybody, and the artifact says so about itself."
  },
  bundle_completeness_check: {
    questions: [],
    parameters: {formats: ["md"], required_formats: ["md"]},
    hint: "Completeness Check reports whether every source was read, whether the formats a later step needs can be produced, and whether a required part came out empty. It concludes nothing about content."
  },
  document_compose: {
    questions: [],
    parameters: {template_path: "", fields: {}, basename: "dokument"},
    hint: "Document Compose fills your own .docx template through the optional report-forge engine. Without that extra installed the run ends blocked with the exact install command, rather than failing on an import."
  },
  mail_merge_compose: {
    questions: [],
    parameters: {template_path: "", contact_book: "", fields: {}, basename: "dokument"},
    hint: "Mail Merge runs the same template once per recipient from your local contact book. Each file is named after the person it was composed for, so a folder of near-identical documents stays sortable."
  },
  guide_compose: {
    questions: [],
    parameters: {formats: ["md"], dedupe_scope: "normalized"},
    hint: "Guide Compose folds a folder into one guide that stands in for its documents. Every paragraph stays a quoted line with its source, so any of them can be checked against the original, and the repeats it folded are counted."
  },
  wiki_export: {
    questions: [],
    parameters: {wiki_dir: ""},
    hint: "Wiki Export writes the corpus as a walkable wiki: one page per document plus an index. Nothing is summarised, because a page that disagrees with the file it came from is worse than no page."
  },
  pattern_mining: {
    questions: [],
    parameters: {formats: ["md"], min_support: 3, focus_terms: []},
    hint: "Pattern Mining reports which lines recur across a large set, with how often and from where. A recurring line is a finding about this corpus, never a rule about the world."
  },
  rater_race: {
    questions: [],
    parameters: {formats: ["md"], coding_scheme: {}, scan_labels: [], rater_a: "", rater_b: ""},
    hint: "Rater Race codes the same material twice under two readings and shows where they part. It reports percent agreement and Cohen's kappa side by side, because the first number alone flatters any scheme where one code dominates."
  },
  reference_check: {
    questions: [],
    parameters: {formats: ["md"], reference_grid: "bescheid_formal", require_complete: false},
    hint: "Reference Check compares your documents against a declared checklist and quotes the line that answers each item. It says present or absent; it never says the document is correct, valid or sufficient, and it is not advice."
  },
  print_action: {
    questions: [],
    parameters: {formats: ["md"], source_id: ""},
    hint: "Print Action prepares a print-ready file and the exact command to print it. It does not invoke the printer: that call returns nothing this run could put in a receipt, so the printing stays your step."
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

function markCurrent(link, active) {
  link.classList.toggle("active", active);
  if (active) link.setAttribute("aria-current", "page");
  else link.removeAttribute("aria-current");
}

function configureRoutedPage() {
  const configuration = pageConfiguration[currentPage];
  for (const link of document.querySelectorAll("[data-page-link]")) {
    markCurrent(link, link.dataset.pageLink === currentPage);
  }
  for (const link of document.querySelectorAll("[data-tab-link]")) {
    markCurrent(link, link.dataset.tabLink === currentTab);
  }
  // The registry is deliberately not filtered: it is the non-thematic list of
  // every contract, which is exactly what someone comes to it for.
  const options = [...$("workflow").options];
  const candidate = options.some((option) => option.value === requestedWorkflow)
    ? requestedWorkflow
    : configuration.defaultWorkflow;
  const selected = options.find((option) => option.value === candidate);
  if (selected) $("workflow").value = selected.value;
}

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
  folders: {
    className: "document-center",
    kicker: "INSIDE THE NAUTILUS",
    title: "Folders",
    text: "The home of your folders: which ones are watched, what is actually on board, and the use cases that work on them. Nothing moves or leaves the Nautilus without being inspectable first.",
    roadmap: "ACTIVE · watched roots + corpus at a glance + the use cases bound to them"
  },
  workflows: {
    className: "analysis-lab",
    kicker: "THE GREAT OBSERVATION WINDOW",
    title: "Workflows",
    text: "Every use case you kept and every specialist that ships with NemoFold, filtered by topic. Look into the deep corpus with Captain Nemo and follow each finding back to its exact source.",
    roadmap: "ACTIVE · my use cases + shipped specialists + standing routines"
  },
  scheduled: {
    className: "folder-routines",
    kicker: "SONAR AND ECHO ROUTINES",
    title: "Standing routines",
    text: "A routine is a workflow with a schedule, not a room of its own. NemoFold registers nothing and starts nothing by itself: the time is recorded, the task file is yours to install.",
    roadmap: "ACTIVE · scheduled use cases · NemoFold installs no timer"
  },
  registry: {
    className: "analysis-lab",
    kicker: "THE INSTRUMENT REGISTRY",
    title: "Registry",
    text: "Every job contract on its own, without a topic: the instruments a use case is built from. Reach for one to diagnose a step, try a parameter, or build something the library does not have yet.",
    roadmap: "ACTIVE · every job contract this server offers · the engine room is their editor"
  },
  artifacts: {
    className: "artifact-library",
    kicker: "THE NAUTILUS LIBRARY",
    title: "Artifacts",
    text: "Reports, ledgers and recovered knowledge are cataloged like shells and sea treasures, with a hash check before a finding receives a green state.",
    roadmap: "ACTIVE · report_studio + verified artifact catalog"
  },
  connections: {
    className: "connections-deck",
    kicker: "SURFACE AND HORIZON",
    title: "Connections",
    text: "The Nautilus has surfaced. Local, provider, Nebius and NemoClaw connections remain separate signals; distant readiness is never presented as proof.",
    roadmap: "STATUS ONLY · platform_proof"
  },
  governance: {
    className: "command-bridge-deck",
    kicker: "THE BRIDGE OF THE NAUTILUS",
    title: "Governance",
    text: "Every lever this vessel answers to, read from the running server: which gates are open, which roots are approved and what the storage policy does with a file once it is filed.",
    roadmap: "ACTIVE · storage_policy + authority instruments"
  }
};

// The scenes did not move with the rooms: they moved to the tabs and filters.
// Porthole for the workflows, echo sounder for the standing routines, library
// for the artifacts, bridge for governance, home port for the folders.
function currentSceneKey() {
  if (currentPage === "processes") {
    if (currentTab === "artifacts") return "artifacts";
    if (currentTab === "registry") return "registry";
    return activeTag === "scheduled" ? "scheduled" : "workflows";
  }
  return currentPage === "overview" ? null : currentPage;
}

function updateVoyageScene(area = null) {
  const key = area || currentSceneKey();
  const scene = voyageScenes[key];
  const container = $("voyageScene");
  if (!scene || !container) return;
  container.className = `voyage-scene ${scene.className}`;
  $("voyageSceneKicker").textContent = scene.kicker;
  $("voyageSceneTitle").textContent = scene.title;
  $("voyageSceneText").textContent = scene.text;
  $("voyageRoadmap").textContent = scene.roadmap;
  const notebookVisible = currentTab === "registry" && $("workflow").value === "evidence_analyst";
  $("researchNotebook").hidden = !notebookVisible;
  if (notebookVisible) updateNotebookSnapshot();
  // The echo sounder belongs to the routines, so it surfaces with their scene.
  if ($("echoCheck")) $("echoCheck").hidden = key !== "scheduled";
}

const workflowCards = {
  smart_inbox: {
    title: "Smart Inbox",
    benefit: "Sort new arrivals into approved folders with an all-or-nothing move you can undo."
  },
  cleanup_rules: {
    title: "Cleanup Rules",
    benefit: "Bulk-route what is already aboard, with suggestions learned only from your own corrections."
  },
  mail_to_case: {
    title: "Mail-to-Case",
    benefit: "Turn approved local .eml files into a source-grounded case dossier with hashed attachments."
  },
  controlled_email: {
    title: "Controlled Email",
    benefit: "Draft a reply locally and hold it at an approval digest until a proven adapter exists."
  },
  storage_policy: {
    title: "Storage Policies",
    benefit: "Decide where a filed document lives, how it is named and how long it stays aboard."
  },
  evidence_analyst: {
    title: "Evidence Analyst",
    benefit: "Ask the corpus a question and read exact quotes, source locations and the gaps that remain."
  },
  bundle_export: {
    title: "Bundle Export",
    benefit: "Build one deterministic bundle with manifest, hashes and visibly listed unreadable entries."
  },
  daily_arrivals: {
    title: "Daily Arrivals",
    benefit: "See what landed in a folder since a snapshot you name, with a short content per file."
  },
  synopsis_merge: {
    title: "Synopsis Merge",
    benefit: "Fold several documents into one synopsis, with every paragraph anchored and conflicts shown."
  },
  fact_distill: {
    title: "Fact Distill",
    benefit: "Pull the quotable facts out of a folder and strike repeats, with every removal listed."
  },
  document_registry: {
    title: "Document Registry",
    benefit: "Turn a folder of documents into one table where every filled cell names its source and line."
  },
  report_studio: {
    title: "Report Studio",
    benefit: "Render one verified analysis into Markdown, TXT, PDF, DOCX and ODT without changing its claims."
  },
  person_registry: {
    title: "Person Registry",
    benefit: "List everyone your documents declare, with a pseudonymous form you can hand over."
  },
  relation_model: {
    title: "Relation Model",
    benefit: "See which links between people a sentence actually states, and read that sentence."
  },
  person_timeline: {
    title: "Person Timeline",
    benefit: "Put stated times on a lane per person and keep the unstated ones visibly open."
  },
  coverage_timeline: {
    title: "Coverage Timeline",
    benefit: "Show when somebody was covered under which tariff, straight from the contract fields."
  },
  cost_timeline: {
    title: "Cost Timeline",
    benefit: "Project upcoming recurring costs and irregular charges without guessing unknown due dates."
  },
  subscription_reconcile: {
    title: "Subscription Reconciliation",
    benefit: "Reconcile declared subscriptions with incoming invoice and message evidence without guessing on ambiguity."
  },
  medication_reconcile: {
    title: "Medication Reconciliation",
    benefit: "Consolidate medications across reports and flag conflicting dosages without medical overreach."
  },
  database_reader: {
    title: "Database Reader",
    benefit: "Safely read inventory or medical specialist databases under guaranteed read-only and schema protection."
  },
  knowledge_composer: {
    title: "Knowledge Composer",
    benefit: "Generate verified documents and worksheets strictly from knowledge bases without hallucinating ungrounded claims."
  },
  alibi_weave: {
    title: "Alibi Weave",
    benefit: "Tell a self-report from an outside confirmation, and see who nothing places at all."
  },
  contradiction_synopsis: {
    title: "Contradiction Synopsis",
    benefit: "Put both wordings of a disagreement side by side with the sources that carry them."
  },
  corpus_query: {
    title: "Corpus Query",
    benefit: "Ask one narrow question of a large bundle and get quoted sentences, not a summary."
  },
  web_research: {
    title: "Web Research",
    benefit: "Search the open web behind four gates and keep only what came back with an address."
  },
  dossier: {
    title: "Dossier",
    benefit: "Collect cited results on a subject into a reading list that refuses to be a verdict."
  },
  bundle_completeness_check: {
    title: "Completeness Check",
    benefit: "Check a bundle is whole before a later step trusts it, and name what is missing."
  },
  document_compose: {
    title: "Document Compose",
    benefit: "Fill your own .docx template, or hear exactly which extra is missing."
  },
  mail_merge_compose: {
    title: "Mail Merge",
    benefit: "One document per recipient from your contact book, each named after them."
  },
  guide_compose: {
    title: "Guide Compose",
    benefit: "Fold many documents into one guide where every line still names its source."
  },
  wiki_export: {
    title: "Wiki Export",
    benefit: "Turn a folder into a walkable wiki whose pages stay equal to their files."
  },
  pattern_mining: {
    title: "Pattern Mining",
    benefit: "See which lines recur across a big pile of logs, how often, and from where."
  },
  rater_race: {
    title: "Rater Race",
    benefit: "Code the same material twice and see exactly where the two readings disagree."
  },
  reference_check: {
    title: "Reference Check",
    benefit: "See which items of a checklist your documents answer, and read the line that does."
  },
  print_action: {
    title: "Print Action",
    benefit: "Get a print-ready file and the exact command, with the printing left to you."
  },
  platform_proof: {
    title: "Platform Proof",
    benefit: "Produce offline evidence about this runtime, without turning local readiness into a cloud proof."
  },
  folder_digest: {
    title: "Folder Digest",
    benefit: "Take a bearing on a folder: what is new, changed, unchanged or gone since the last snapshot."
  },
  version_resolver: {
    title: "Version Resolver",
    benefit: "Resolve which document version is the valid one and compare the wording line by line."
  },
  contact_monitor: {
    title: "Contact Monitor",
    benefit: "Surface who the sources say is responsible, and compare that against an earlier snapshot."
  }
};

const SVG_NS = "http://www.w3.org/2000/svg";

function instrumentIcon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", `instrument-icon ${name}`);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#icon-${name}`);
  svg.append(use);
  return svg;
}

const overlayQuery = globalThis.matchMedia?.("(max-width: 680px)");
let engineReturnFocus = null;

function engineDrawerIsOpen() {
  return $("engineRoom")?.dataset.open === "true";
}

function syncDrawerModality() {
  const drawer = $("engineRoom");
  if (!drawer) return;
  // The drawer only traps the page on the mobile full-surface overlay. Beside a
  // readable page it is a panel, and announcing it as a modal would lie.
  if (overlayQuery?.matches && engineDrawerIsOpen()) {
    drawer.setAttribute("role", "dialog");
    drawer.setAttribute("aria-modal", "true");
  } else {
    drawer.removeAttribute("role");
    drawer.removeAttribute("aria-modal");
  }
}

function setEngineDrawer(open, {moveFocus = true} = {}) {
  const drawer = $("engineRoom");
  if (!drawer) return;
  const wasOpen = engineDrawerIsOpen();
  drawer.dataset.open = open ? "true" : "false";
  document.body.dataset.engineRoom = open ? "open" : "closed";
  $("engineHandle")?.setAttribute("aria-expanded", open ? "true" : "false");
  syncDrawerModality();
  if (open && !wasOpen) {
    engineReturnFocus = document.activeElement;
    if (moveFocus) ($("engineClose") || drawer).focus({preventScroll: true});
    return;
  }
  if (!open && wasOpen) {
    const trigger = engineReturnFocus;
    engineReturnFocus = null;
    if (moveFocus && trigger instanceof HTMLElement && document.contains(trigger)) {
      trigger.focus({preventScroll: true});
    }
  }
}

const reducedMotionQuery = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)");
let wizardSurfaceEnabled = false;
let lastVoyageRequest = null;

function pageForWorkflow(workflow) {
  const match = Object.entries(pageConfiguration)
    .find(([, configuration]) => configuration.workflows.includes(workflow));
  return match ? match[0] : "document";
}

function routeForPage(page) {
  for (const [path, name] of pageByPath) if (name === page) return path;
  return "/document-center";
}

function deskLine(parent, tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  parent.append(node);
  return node;
}

function renderVoyagePlan(plan) {
  const answer = $("deskAnswer");
  answer.textContent = "";
  lastVoyageRequest = plan.request_text;

  for (const note of plan.notes || []) deskLine(answer, "p", "desk-note", note);

  if (plan.steps?.length) {
    const heading = deskLine(answer, "p", "kicker", "PREPARED VOYAGE");
    heading.id = "voyageHeading";
    const list = deskLine(answer, "div", "voyage-steps");
    list.setAttribute("role", "list");
    for (const step of plan.steps) {
      const card = deskLine(list, "article", "voyage-step");
      card.setAttribute("role", "listitem");
      deskLine(card, "span", "voyage-order", `STEP ${step.order} · ${step.workflow}`);
      deskLine(card, "b", null, step.title);
      deskLine(card, "p", null, step.why);
      if (step.reads_previous_step) {
        deskLine(card, "small", "voyage-handoff", "Reads the previous step's output.");
      }
      if (step.questions_to_user?.length) {
        deskLine(card, "span", "voyage-open-label", "STILL OPEN");
        const open = deskLine(card, "ul", "voyage-open");
        for (const question of step.questions_to_user) deskLine(open, "li", null, question);
      }
    }
  }

  for (const item of plan.unavailable || []) {
    const block = deskLine(answer, "div", "voyage-unavailable");
    deskLine(block, "span", null, `NOT ACTIVE · ${item.label}`);
    deskLine(block, "p", null, item.reason);
    deskLine(block, "p", "voyage-approximation", item.approximation);
  }

  if (plan.recurring?.requested) {
    const block = deskLine(answer, "div", "voyage-recurring");
    deskLine(block, "span", null, "REPETITION");
    deskLine(block, "p", null, plan.recurring.message);
    const options = deskLine(block, "ul", null);
    for (const option of plan.recurring.options) deskLine(options, "li", null, option);
  }

  if (plan.steps?.length) {
    const actions = deskLine(answer, "div", "voyage-actions");
    const prepare = document.createElement("button");
    prepare.type = "button";
    prepare.id = "deskPrepare";
    prepare.className = "card-open";
    prepare.append(instrumentIcon("wheel"), "Prepare voyage");
    prepare.addEventListener("click", prepareVoyage);
    actions.append(prepare);
    deskLine(
      actions,
      "small",
      null,
      "Preparing writes drafts into the job inbox. It runs nothing and sends nothing."
    );
  }
}

async function askTheCaptain(event) {
  event?.preventDefault();
  const answer = $("deskAnswer");
  if (!wizardSurfaceEnabled) {
    answer.textContent = "";
    deskLine(
      answer,
      "p",
      "desk-note",
      "The captain's desk is a loopback-only surface and stays closed on this server."
    );
    return;
  }
  const text = $("deskRequest").value.trim();
  if (!text) {
    answer.textContent = "";
    deskLine(answer, "p", "desk-note", "Write one sentence about what you need.");
    return;
  }
  answer.textContent = "";
  deskLine(answer, "p", "desk-note", "Charting…");
  try {
    const response = await fetch("/api/wizard", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text, context: {input_roots: lines($("deskRoots").value)}})
    });
    const plan = await response.json();
    if (!response.ok || plan.ok !== true) {
      throw new Error(plan.detail || plan.error || `request failed (${response.status})`);
    }
    renderVoyagePlan(plan);
  } catch (error) {
    answer.textContent = "";
    deskLine(answer, "p", "desk-note", `No plan: ${error.message}`);
  }
}

async function prepareVoyage() {
  const answer = $("deskAnswer");
  const button = $("deskPrepare");
  if (button) button.disabled = true;
  try {
    const response = await fetch("/api/wizard-prepare", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        text: lastVoyageRequest || $("deskRequest").value.trim(),
        context: {input_roots: lines($("deskRoots").value)}
      })
    });
    const result = await response.json();
    if (!response.ok || result.prepared !== true) {
      throw new Error(result.detail || result.error || `request failed (${response.status})`);
    }
    const receipt = deskLine(answer, "div", "voyage-receipt");
    deskLine(receipt, "span", null, `${result.drafts.length} DRAFTS PREPARED`);
    const list = deskLine(receipt, "ul", null);
    for (const draft of result.drafts) deskLine(list, "li", null, draft.name);
    const first = result.drafts[0];
    const page = pageForWorkflow(first.workflow);
    const link = deskLine(receipt, "a", "voyage-link", "Open the engine room →");
    link.href = `${routeForPage(page)}?workflow=${encodeURIComponent(first.workflow)}`;
    deskLine(
      receipt,
      "small",
      null,
      "They wait in the prepared job inbox. Nothing has run and no approval was stored."
    );
    receipt.scrollIntoView({behavior: reducedMotionQuery?.matches ? "auto" : "smooth",
      block: "nearest"});
  } catch (error) {
    deskLine(answer, "p", "desk-note", `Not prepared: ${error.message}`);
  } finally {
    if (button) button.disabled = false;
  }
}

function toggleCollapse(button) {
  const panel = $(button.getAttribute("aria-controls"));
  if (!panel) return;
  const expanded = button.getAttribute("aria-expanded") === "true";
  button.setAttribute("aria-expanded", expanded ? "false" : "true");
  if (button.dataset.animated !== "true") {
    panel.hidden = expanded;
    return;
  }
  // The hidden attribute keeps the closed panel out of the tab order, but a
  // display:none box cannot be transitioned. So opening reveals first and
  // animates on the next frame, and closing hides only once the fold is done.
  const container = panel.parentElement;
  if (!expanded) {
    panel.hidden = false;
    if (reducedMotionQuery?.matches) container.dataset.open = "true";
    else requestAnimationFrame(() => { container.dataset.open = "true"; });
    return;
  }
  container.dataset.open = "false";
  if (reducedMotionQuery?.matches) {
    panel.hidden = true;
    return;
  }
  globalThis.setTimeout(() => {
    if (container.dataset.open !== "true") panel.hidden = true;
  }, 420);
}

function prepareWorkflow(workflow) {
  const select = $("workflow");
  const option = [...select.options].find((item) => item.value === workflow && !item.disabled);
  if (!option) return;
  select.value = workflow;
  applyWorkflowDefaults();
  renderTaskCards();
  setEngineDrawer(true);
}

// D-036b: the registry lists every contract, and at two dozen of them a flat
// deck stops being a list and becomes a wall. The groups are by what the
// contract does to your files, which is the distinction a reader is actually
// making when they scan it.
const registryGroups = [
  {title: "Intake and filing", workflows: ["smart_inbox", "cleanup_rules", "storage_policy"]},
  {title: "Mail", workflows: ["mail_to_case", "controlled_email"]},
  {title: "Reading a corpus", workflows: ["evidence_analyst", "bundle_export", "fact_distill",
    "synopsis_merge", "document_registry", "corpus_query", "pattern_mining"]},
  {title: "Case chronicle", workflows: ["person_registry", "relation_model", "person_timeline",
    "coverage_timeline", "cost_timeline", "subscription_reconcile", "medication_reconcile", "database_reader", "alibi_weave", "contradiction_synopsis"]},
  {title: "Folder routines", workflows: ["folder_digest", "daily_arrivals", "version_resolver",
    "contact_monitor"]},
  {title: "Outward and status", workflows: ["web_research", "dossier", "platform_proof"]},
  {title: "Checks and output", workflows: ["bundle_completeness_check", "reference_check",
    "rater_race", "report_studio", "guide_compose", "wiki_export",
    "document_compose", "mail_merge_compose", "knowledge_composer", "print_action"]}
];


// --------------------------------------------------------------------------- //
// A run that asked back rather than guessing
// --------------------------------------------------------------------------- //

function renderAskBack(report) {
  const panel = $("askBack");
  if (!panel) return;
  const path = (report?.artifacts || []).find(
    (item) => item.format === "needs-user-input"
  );
  if (!report || report.metadata?.needs_user_input !== true || !path) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  $("askBackNote").textContent = String(report.metadata.outcome_note || "");
  const list = $("askBackList");
  list.textContent = "";
  $("askBackState").textContent = "";
  // The questions travel in the artifact, so the surface reads them from there
  // rather than re-deriving what the run already decided.
  fetch(artifactViewUrl($("outputDir").value, path.path))
    .then((reply) => reply.json())
    .then((payload) => {
      for (const question of payload.questions || []) {
        const row = deskLine(list, "div", "ask-row");
        row.setAttribute("role", "listitem");
        const label = document.createElement("label");
        label.textContent = question.prompt;
        const input = document.createElement("input");
        input.dataset.answerField = question.field;
        input.autocomplete = "off";
        input.placeholder = question.kind;
        label.append(input);
        row.append(label);
        deskLine(row, "small", "ask-why", question.why || "");
      }
    })
    .catch((error) => {
      $("askBackState").textContent = `The questions could not be read: ${error.message}`;
    });
}

function applyAnswers() {
  const answers = {};
  for (const input of document.querySelectorAll("[data-answer-field]")) {
    const value = input.value.trim();
    if (value) answers[input.dataset.answerField] = value;
  }
  if (!Object.keys(answers).length) {
    $("askBackState").textContent = "Nothing to take over: no field was answered.";
    return;
  }
  // The answers become declared parameters of the same contract, so the next
  // run carries them the way any other setting is carried - visible, editable
  // and part of what a draft would store.
  let parameters = {};
  try {
    parameters = JSON.parse($("parameters").value || "{}");
  } catch {
    parameters = {};
  }
  parameters.answers = {...(parameters.answers || {}), ...answers};
  $("parameters").value = JSON.stringify(parameters, null, 2);
  $("askBackState").textContent =
    `Taken over: ${Object.keys(answers).length} answer(s) are now in the contract. `
    + "Run it again to continue.";
}

function renderTaskCards() {
  const list = $("taskCardList");
  if (!list) return;
  // Non-thematic on purpose: the registry lists every contract the server
  // actually offers, in the order the contract dropdown holds them.
  const workflows = [...$("workflow").options]
    .map((option) => option.value)
    .filter((item) => workflowCards[item]);
  list.textContent = "";
  if (!workflows.length) {
    const note = document.createElement("p");
    note.textContent = "This server offers no job contract.";
    list.append(note);
    return;
  }
  const active = $("workflow").value;
  const grouped = new Set();
  for (const group of registryGroups) {
    const present = group.workflows.filter((item) => workflows.includes(item));
    if (!present.length) continue;
    const heading = document.createElement("p");
    heading.className = "kicker task-group";
    heading.textContent = group.title.toUpperCase();
    list.append(heading);
    for (const workflow of present) {
      grouped.add(workflow);
      list.append(taskCard(workflow, active));
    }
  }
  // Anything a group forgot still shows, rather than disappearing because a
  // list somewhere was not updated.
  const ungrouped = workflows.filter((item) => !grouped.has(item));
  if (ungrouped.length) {
    const heading = document.createElement("p");
    heading.className = "kicker task-group";
    heading.textContent = "NOT YET GROUPED";
    list.append(heading);
    for (const workflow of ungrouped) list.append(taskCard(workflow, active));
  }
}

function taskCard(workflow, active) {
  {
    const card = document.createElement("article");
    card.className = "task-card";
    card.setAttribute("role", "listitem");
    if (workflow === active) card.dataset.active = "true";
    const title = document.createElement("b");
    title.textContent = workflowCards[workflow].title;
    const benefit = document.createElement("p");
    benefit.textContent = workflowCards[workflow].benefit;
    const technical = document.createElement("span");
    technical.textContent = workflow;
    const button = document.createElement("button");
    button.type = "button";
    button.className = workflow === active ? "card-open secondary" : "card-open";
    button.append(
      instrumentIcon("wheel"),
      workflow === active ? "Selected · open engine room" : "Prepare in engine room"
    );
    button.addEventListener("click", () => prepareWorkflow(workflow));
    card.append(technical, title, benefit, button);
    return card;
  }
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function renderHomeGlance(glance) {
  $("glanceFiles").textContent = glance.truncated
    ? `${glance.total_files}+ files`
    : `${glance.total_files} files`;
  $("glanceBytes").textContent = formatBytes(glance.total_bytes);
  const formats = Object.entries(glance.by_format || {});
  $("glanceFormats").textContent = formats.length
    ? formats.map(([name, count]) => `${name} ${count}`).join(" · ")
    : "none";
  const list = $("glanceNewest");
  list.textContent = "";
  const newest = Array.isArray(glance.newest) ? glance.newest : [];
  if (!newest.length) {
    const note = document.createElement("p");
    note.textContent = "This root holds no readable file yet.";
    list.append(note);
  }
  for (const item of newest) {
    const row = document.createElement("div");
    const name = document.createElement("b");
    name.textContent = item.relative_path || item.name;
    const meta = document.createElement("span");
    meta.textContent = `${item.modified} · ${formatBytes(item.bytes)}`;
    row.append(name, meta);
    list.append(row);
  }
  $("glanceState").textContent = glance.truncated
    ? `Root ${glance.root} · counting stopped at the bounded file cap; totals are a floor, not the whole hold.`
    : `Root ${glance.root} · counts and modification times only. No file was opened.`;
}

async function loadHomeGlance() {
  if (!$("homeGlance")) return;
  const requested = $("homeGlanceRoot").value.trim();
  $("glanceState").textContent = "Looking around…";
  try {
    const response = await fetch("/api/corpus-glance", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: requested || null})
    });
    const payload = await response.json();
    if (!response.ok || payload.ok !== true) {
      throw new Error(payload.detail || payload.error || `request failed (${response.status})`);
    }
    $("homeGlanceRoot").value = payload.root;
    renderHomeGlance(payload);
  } catch (error) {
    $("glanceState").textContent = `No overview: ${error.message}`;
    $("glanceNewest").textContent = "";
    const note = document.createElement("p");
    note.textContent = "The server refused or could not read this root. Nothing was inferred.";
    $("glanceNewest").append(note);
  }
}

async function loadEcho() {
  if (!$("echoCheck")) return;
  const outputDir = $("echoOutputDir").value.trim() || $("outputDir").value.trim();
  const list = $("echoList");
  list.textContent = "Listening…";
  try {
    const response = await fetch("/api/artifacts", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({output_dir: outputDir})
    });
    const payload = await response.json();
    if (!response.ok || payload.ok !== true) {
      throw new Error(payload.detail || payload.error || `request failed (${response.status})`);
    }
    const routineWorkflows = new Set(pageConfiguration.routines.workflows);
    const runs = (Array.isArray(payload.runs) ? payload.runs : [])
      .filter((run) => routineWorkflows.has(run.workflow));
    list.textContent = "";
    if (!runs.length) {
      const note = document.createElement("p");
      note.textContent = "No echo from this direction yet — start a routine below.";
      list.append(note);
      return;
    }
    for (const run of runs) {
      const row = document.createElement("div");
      row.className = "echo-row";
      row.dataset.status = run.status || "unknown";
      const ping = document.createElement("i");
      ping.setAttribute("aria-hidden", "true");
      const label = document.createElement("b");
      label.textContent = `${workflowCards[run.workflow]?.title || run.workflow} · ${run.status}`;
      const meta = document.createElement("span");
      meta.textContent = run.recorded_at
        ? `${run.run_id} · ledger written ${run.recorded_at}`
        : `${run.run_id} · ledger write time unavailable`;
      row.append(ping, label, meta);
      list.append(row);
    }
  } catch (error) {
    list.textContent = "";
    const note = document.createElement("p");
    note.textContent = `No echo read: ${error.message}`;
    list.append(note);
  }
}

function setInstrument(id, open, openText, closedText) {
  const readout = $(id);
  if (!readout) return;
  readout.textContent = open ? openText : closedText;
  const instrument = readout.closest(".instrument");
  if (instrument) instrument.dataset.state = open ? "open" : "closed";
}

function renderCommandBridge(status) {
  if (!$("commandBridge")) return;
  setInstrument(
    "bridgeActionGate",
    status.apply_actions_allowed === true,
    "APPLY GATE OPEN · file actions may be executed",
    "DRY-RUN ONLY · plans stay reversible"
  );
  setInstrument(
    "bridgeExternalGate",
    status.external_models_allowed === true,
    "EXTERNAL GATE OPEN · a transfer still needs per-run approval",
    "EXTERNAL GATE CLOSED · evidence stays on this host"
  );
  setInstrument(
    "bridgeNetworkGate",
    status.network_exposed !== true,
    "LOOPBACK BERTH · reachable from this machine only",
    "NETWORK EXPOSED · provider and browser surfaces disabled"
  );
  const rootCount = Number(status.approved_root_count || 0);
  $("bridgeRootCount").textContent = rootCount === 1 ? "1 approved root" : `${rootCount} approved roots`;
  const budget = Number(status.max_external_cost_usd || 0);
  $("bridgeBudget").textContent = budget > 0
    ? `${budget.toFixed(2)} USD per run`
    : "0.00 USD · no external spend permitted";
  const cores = Array.isArray(status.cores) ? status.cores : [];
  $("bridgeCores").textContent = `${cores.length} shared cores`;
  const workflows = Array.isArray(status.workflows) ? status.workflows : [];
  $("bridgeWorkflows").textContent = `${workflows.length} contracted workflows`;
  const roots = Array.isArray(status.approved_roots) ? status.approved_roots : [];
  const list = $("bridgeRoots");
  list.textContent = "";
  if (!roots.length) {
    const note = document.createElement("p");
    note.textContent = rootCount
      ? "Root locations are withheld on a public or network-exposed server. The count above remains authoritative."
      : "This server was started without an approved root. No workflow can read a file.";
    list.append(note);
    return;
  }
  for (const root of roots) {
    const row = document.createElement("div");
    const label = document.createElement("span");
    label.textContent = "APPROVED ROOT";
    const value = document.createElement("b");
    value.textContent = root;
    row.append(label, value);
    list.append(row);
  }
}

function renderWebRoute(status) {
  const cell = $("connectionWeb");
  if (!cell) return;
  if (status.web_search_adapter === undefined) {
    cell.textContent = "Not offered on this server";
    return;
  }
  const parts = [
    status.web_search_allowed ? "gate open" : "gate closed",
    status.web_search_key_present ? "key present" : "no key",
    status.web_search_proven ? "proven" : "unproven",
  ];
  cell.textContent = `${status.web_search_adapter}: ${parts.join(" · ")}`;
}

function renderConnectionStatus(status) {
  $("connectionLocal").textContent = status.ok
    ? `Local API responding · ${status.mode}`
    : "Local API unavailable";
  $("connectionProvider").textContent = status.provider_runtime_ready
    ? "Verified provider execution receipt available"
    : "Configured routes only · no verified execution receipt";
  $("connectionTransfer").textContent = status.transfer_performed
    ? "Transfer recorded: true"
    : `Transfer recorded: false · external gate ${status.external_models_allowed ? "available" : "closed"}`;
  $("connectionCloud").textContent = status.cloud_proof
    ? "True · verified live evidence"
    : "False · no live competition proof";
  const registry = $("connectionRegistry");
  registry.replaceChildren();
  const providers = Array.isArray(status.providers) ? status.providers : [];
  if (!providers.length) {
    const empty = document.createElement("p");
    empty.textContent = "No provider adapters are exposed by this runtime.";
    registry.append(empty);
    return;
  }
  for (const provider of providers) {
    const row = document.createElement("article");
    row.className = provider.external_transfer ? "connection-route external" : "connection-route loopback";
    const identity = document.createElement("div");
    const label = document.createElement("h3");
    label.textContent = provider.label;
    const id = document.createElement("small");
    id.textContent = provider.provider_id;
    identity.append(label, id);
    const transport = document.createElement("div");
    const transportLabel = document.createElement("span");
    transportLabel.textContent = "TRANSPORT";
    const transportValue = document.createElement("b");
    transportValue.textContent = provider.transport;
    transport.append(transportLabel, transportValue);
    const boundary = document.createElement("div");
    const boundaryLabel = document.createElement("span");
    boundaryLabel.textContent = "BOUNDARY";
    const boundaryValue = document.createElement("b");
    boundaryValue.textContent = provider.external_transfer
      ? "External · one-run approval"
      : "Loopback · local only";
    boundary.append(boundaryLabel, boundaryValue);
    const proof = document.createElement("div");
    const proofLabel = document.createElement("span");
    proofLabel.textContent = "CURRENT CLAIM";
    const proofValue = document.createElement("b");
    proofValue.textContent = provider.competition_proof
      ? "Competition proof recorded"
      : "Configured · execution unverified";
    proof.append(proofLabel, proofValue);
    row.append(identity, transport, boundary, proof);
    registry.append(row);
  }
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

function fillOverrideProviders(status) {
  const select = $("libraryOverrideProvider");
  if (!select) return;
  for (const provider of status.providers || []) {
    const option = document.createElement("option");
    option.value = provider.provider_id;
    option.textContent = provider.external_transfer
      ? `${provider.label} · sends off this host`
      : provider.label;
    select.append(option);
  }
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
  if (!defaults) return;
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
    renderAskBack(report);
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
  if (["outputDir", "homeGlanceRoot"].includes(folderTargetId)) {
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

async function loadHomeModules() {
  if ($("homeGlance")) {
    if (!$("homeGlanceRoot").value.trim()) {
      $("homeGlanceRoot").value = lines($("inputRoots").value)[0] || "";
    }
    if (folderPickerEnabled) await loadHomeGlance();
    else {
      $("glanceState").textContent =
        "The corpus overview is a loopback-only surface and stays closed here.";
    }
  }
  if ($("echoCheck")) {
    if (!$("echoOutputDir").value.trim()) $("echoOutputDir").value = $("outputDir").value;
    if (artifactSurfaceEnabled) await loadEcho();
    else {
      $("echoList").textContent = "";
      const note = document.createElement("p");
      note.textContent = "Echo sounding is a loopback-only surface and stays closed here.";
      $("echoList").append(note);
    }
  }
}

const governanceCopy = {
  policies: {
    kicker: "POLICIES",
    title: "What holds, in general.",
    lede: "A policy is a rule set you can bind to a voyage or to one of its steps."
      + " It is a written expectation, not a gate: allow roots, privacy mode, action"
      + " mode and the per-run approvals still decide."
  },
  rules: {
    kicker: "RULES",
    title: "One sentence at a time.",
    lede: "A rule is a single sentence you can hold in your head. Bound to six"
      + " voyages it stays one object, so changing it changes all six - and the"
      + " rule itself shows you which six."
  }
};

let editingPolicy = null;
let knownPolicies = [];

function policyFormKind() {
  return $("policyKind").value;
}

function syncPolicyFormKind() {
  $("policyRightsRow").hidden = policyFormKind() !== "rights_profile";
  $("policyBodyRow").hidden = policyFormKind() !== "cleanup_rules";
}

function resetPolicyForm() {
  editingPolicy = null;
  $("policyFormMode").textContent = "NEW ENTRY";
  $("policyFormTitle").textContent = "Write it down once.";
  $("policyName").value = "";
  $("policyDescription").value = "";
  $("policyStatements").value = "";
  $("policyKind").value = "custom";
  $("policyRights").value = "draft_only";
  $("policyDefault").checked = false;
  $("policyFormState").textContent = "";
  syncPolicyFormKind();
}

function editPolicy(policy) {
  editingPolicy = policy;
  $("policyFormMode").textContent = `EDITING ${policy.form.toUpperCase()}`;
  $("policyFormTitle").textContent = policy.name;
  $("policyName").value = policy.name;
  $("policyDescription").value = policy.description || "";
  $("policyStatements").value = policy.statements.join("\n");
  $("policyKind").value = policy.kind;
  if (policy.kind === "rights_profile") {
    $("policyRights").value = policy.body.rights || "draft_only";
  }
  if (policy.kind === "cleanup_rules") {
    $("policyBody").value = JSON.stringify(policy.body.rules || [], null, 2);
  }
  $("policyDefault").checked = policy.applies_by_default === true;
  $("policyFormState").textContent = "";
  syncPolicyFormKind();
  $("policyName").focus();
}

function policyPayload() {
  const statements = lines($("policyStatements").value);
  const payload = {
    name: $("policyName").value.trim(),
    // The tab decides the shape: the Rules tab writes rules, Policies writes
    // rule sets. Nobody has to learn a discriminator to write one sentence.
    form: currentTab === "rules" ? "rule" : "policy",
    kind: policyFormKind(),
    description: $("policyDescription").value.trim(),
    statements,
    applies_by_default: $("policyDefault").checked
  };
  if (editingPolicy) payload.policy_id = editingPolicy.policy_id;
  if (payload.kind === "rights_profile") payload.body = {rights: $("policyRights").value};
  if (payload.kind === "cleanup_rules") payload.body = {rules: JSON.parse($("policyBody").value)};
  return payload;
}

async function savePolicy(event) {
  event?.preventDefault();
  const state = $("policyFormState");
  try {
    const response = await fetch("/api/policies", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(policyPayload())
    });
    const payload = await response.json();
    if (!response.ok || payload.ok !== true) {
      throw new Error(payload.detail || payload.error || `request failed (${response.status})`);
    }
    resetPolicyForm();
    state.textContent = "Saved.";
    await loadGovernanceRegister();
  } catch (error) {
    state.textContent = `Not saved: ${error.message}`;
  }
}

async function deletePolicy(policy) {
  const state = $("policyFormState");
  try {
    const response = await fetch("/api/policy-delete", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({policy_id: policy.policy_id})
    });
    const payload = await response.json();
    if (!response.ok || payload.ok !== true) {
      throw new Error(payload.detail || payload.error || `request failed (${response.status})`);
    }
    if (editingPolicy && editingPolicy.policy_id === policy.policy_id) resetPolicyForm();
    state.textContent = `Deleted ${policy.name}.`;
    await loadGovernanceRegister();
  } catch (error) {
    state.textContent = `Not deleted: ${error.message}`;
  }
}

async function bindPolicy(policy, voyageId, stepIndex, bound) {
  const state = $("policyFormState");
  try {
    const response = await fetch("/api/policy-bind", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        policy_id: policy.policy_id,
        target: stepIndex ? "step" : "voyage",
        voyage_id: voyageId,
        step_index: stepIndex || null,
        bound
      })
    });
    const payload = await response.json();
    if (!response.ok || payload.ok !== true) {
      throw new Error(payload.detail || payload.error || `request failed (${response.status})`);
    }
    state.textContent = bound ? "Bound." : "Binding released.";
    await loadGovernanceRegister();
  } catch (error) {
    state.textContent = `Not bound: ${error.message}`;
  }
}

function renderPolicyBinder(card, policy) {
  const bindable = libraryEntries.filter((entry) => entry.editable);
  if (!bindable.length) return;
  const row = deskLine(card, "div", "policy-binder");
  const select = document.createElement("select");
  select.setAttribute("aria-label", `Bind ${policy.name} to a voyage`);
  for (const entry of bindable) {
    const option = document.createElement("option");
    option.value = entry.voyage_id;
    option.textContent = entry.name;
    select.append(option);
  }
  const step = document.createElement("input");
  step.type = "number";
  step.min = "0";
  step.value = "0";
  step.setAttribute("aria-label", "Step number, 0 for the whole voyage");
  const bind = document.createElement("button");
  bind.type = "button";
  bind.className = "secondary";
  bind.textContent = "Bind";
  bind.addEventListener("click", () =>
    bindPolicy(policy, select.value, Number(step.value) || 0, true));
  row.append(select, step, bind);
  deskLine(row, "small", null, "Step 0 binds the whole voyage.");
}

function renderPolicyCard(list, policy) {
  const card = deskLine(list, "article", "policy-card");
  card.dataset.form = policy.form;
  card.setAttribute("role", "listitem");
  deskLine(card, "span", null, `${policy.form.toUpperCase()} · ${policy.kind}`);
  deskLine(card, "b", null, policy.name);
  if (policy.description) deskLine(card, "p", null, policy.description);
  const statements = deskLine(card, "ul", null);
  for (const statement of policy.statements) deskLine(statements, "li", null, statement);
  const bindings = policy.bindings || [];
  deskLine(
    card,
    "p",
    "policy-bindings",
    bindings.length
      ? `Bound to ${bindings.length} place(s): ` + bindings
        .map((item) => item.target === "step"
          ? `${item.voyage_id} step ${item.step_index}`
          : item.voyage_id)
        .join(" · ")
      : "Not bound to anything yet."
  );
  if (policy.applies_by_default) {
    deskLine(card, "span", "policy-default", "APPLIES BY DEFAULT");
  }
  const actions = deskLine(card, "div", "policy-actions");
  for (const [label, handler] of [["Edit", () => editPolicy(policy)],
                                  ["Delete", () => deletePolicy(policy)]]) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = label;
    button.addEventListener("click", handler);
    actions.append(button);
  }
  for (const binding of bindings) {
    const release = document.createElement("button");
    release.type = "button";
    release.className = "secondary";
    release.textContent = binding.target === "step"
      ? `Release step ${binding.step_index}`
      : "Release voyage binding";
    release.addEventListener("click", () =>
      bindPolicy(policy, binding.voyage_id, binding.step_index || 0, false));
    actions.append(release);
  }
  renderPolicyBinder(card, policy);
}

function renderGovernanceRegister(payload) {
  const copy = governanceCopy[currentTab] || governanceCopy.policies;
  $("governanceRegisterKicker").textContent = copy.kicker;
  $("governanceRegisterTitle").textContent = copy.title;
  $("governanceRegisterLede").textContent = copy.lede;
  $("governanceDefaultRights").textContent = payload.default_rights;
  const list = $("governanceList");
  list.textContent = "";
  list.setAttribute("role", "list");
  knownPolicies = payload.policies || [];
  const wanted = currentTab === "rules" ? "rule" : "policy";
  const shown = knownPolicies.filter((item) => item.form === wanted);
  if (!shown.length) {
    libraryNote(
      list,
      wanted === "rule"
        ? "No rule written yet. A rule is one sentence that holds across voyages."
        : "No policy written yet. A policy is a rule set you can bind to a voyage."
    );
  }
  for (const policy of shown) renderPolicyCard(list, policy);
  const exceptions = $("governanceExceptions");
  exceptions.textContent = "";
  if (!(payload.exceptions || []).length) {
    libraryNote(exceptions, "Nothing deviates. Every saved voyage follows the defaults.");
    return;
  }
  for (const row of payload.exceptions) {
    const item = deskLine(exceptions, "div", "exception-row");
    deskLine(item, "b", null, row.voyage_name || row.voyage_id);
    deskLine(
      item,
      "span",
      null,
      row.scope === "step" ? `${row.subject} · step ${row.step_index}` : row.subject
    );
    deskLine(item, "small", null, `${row.note} (default: ${row.baseline})`);
  }
}

async function loadKnownPolicies() {
  // Only the list, so the library can offer bindings outside governance.
  try {
    const response = await fetch("/api/policies");
    const payload = await response.json();
    if (response.ok && payload.ok === true) knownPolicies = payload.policies || [];
  } catch {
    knownPolicies = [];
  }
}

async function loadGovernanceRegister() {
  const list = $("governanceList");
  if (!list || currentPage !== "governance") return;
  if (!policySurfaceEnabled) {
    list.textContent = "";
    libraryNote(list, "The policy register is a loopback-only surface and stays closed here.");
    return;
  }
  try {
    if (!libraryEntries.length && voyageSurfaceEnabled) {
      const listed = await fetch("/api/voyages");
      const known = await listed.json();
      if (listed.ok && known.ok === true) libraryEntries = known.voyages || [];
    }
    const response = await fetch("/api/policies");
    const payload = await response.json();
    if (!response.ok || payload.ok !== true) {
      throw new Error(payload.detail || payload.error || `request failed (${response.status})`);
    }
    renderGovernanceRegister(payload);
  } catch (error) {
    list.textContent = "";
    libraryNote(list, `The register could not be read: ${error.message}`);
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
    wizardSurfaceEnabled = status.wizard_surface_enabled === true;
    voyageSurfaceEnabled = status.voyage_surface_enabled === true;
    policySurfaceEnabled = status.policy_surface_enabled === true;
    configureProviders(status);
    fillOverrideProviders(status);
    renderConnectionStatus(status);
    renderWebRoute(status);
    renderCommandBridge(status);
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
      configureRoutedPage();
      applyWorkflowDefaults();
      updateProviderPanel();
      for (const button of document.querySelectorAll("[data-folder-target]")) button.disabled = true;
    } else {
      configureRoutedPage();
      applyWorkflowDefaults();
      for (const button of document.querySelectorAll("[data-folder-target]")) {
        button.disabled = !folderPickerEnabled;
      }
    }
    renderTaskCards();
    if ($("deskRoots") && !$("deskRoots").value.trim()) {
      $("deskRoots").value = lines($("inputRoots").value)[0] || "";
    }
    await loadDraftInbox();
    await loadResearchNotebooks();
    await loadArtifacts();
    await loadHomeModules();
    await loadLibrary();
    await loadGovernanceRegister();
    if (currentPage !== "governance" && policySurfaceEnabled) await loadKnownPolicies();
    $("systemState").textContent = status.live_runtime_ready
      ? "Verified live runtime receipt"
      : publicDemo ? "Public synthetic demo · read-only" : "Local core responding · cloud proof absent";
    $("systemState").classList.add(status.live_runtime_ready ? "ok" : "warn");
    $("cloudBadge").textContent = `Cloud proof: ${status.cloud_proof}`;
  } catch {
    $("systemState").textContent = "Runtime unavailable";
    $("systemState").classList.add("warn");
  }
}

configureRoutedPage();
renderTaskCards();
if ($("engineHandle")) {
  $("engineHandle").addEventListener("click", () => setEngineDrawer(!engineDrawerIsOpen()));
}
if ($("engineClose")) $("engineClose").addEventListener("click", () => setEngineDrawer(false));
overlayQuery?.addEventListener?.("change", syncDrawerModality);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && engineDrawerIsOpen() && !document.querySelector("dialog[open]")) {
    setEngineDrawer(false);
  }
});
document.addEventListener("click", (event) => {
  const anchor = event.target.closest?.("[data-collapse]");
  if (anchor) toggleCollapse(anchor);
});
// A ?workflow= deep link names one task, so the contract opens with it. Focus
// stays where the browser put it; the reader asked for a page, not a dialog.
if (requestedWorkflow && currentTab === "registry") {
  setEngineDrawer(true, {moveFocus: false});
}
$("runId").value = "";
$("workflow").addEventListener("change", () => { applyWorkflowDefaults(); renderTaskCards(); });
if ($("deskForm")) $("deskForm").addEventListener("submit", askTheCaptain);
if ($("libraryRefresh")) $("libraryRefresh").addEventListener("click", loadLibrary);
if ($("governanceRefresh")) {
  $("governanceRefresh").addEventListener("click", loadGovernanceRegister);
}
if ($("policyForm")) {
  $("policyForm").addEventListener("submit", savePolicy);
  $("policyKind").addEventListener("change", syncPolicyFormKind);
  $("policyReset").addEventListener("click", resetPolicyForm);
  syncPolicyFormKind();
}
if ($("libraryClose")) {
  $("libraryClose").addEventListener("click", () => { openVoyage = null; renderVoyageDetail(); });
}
if ($("libraryRun")) $("libraryRun").addEventListener("click", runOpenVoyage);
if ($("librarySave")) $("librarySave").addEventListener("click", saveVoyageChanges);
if ($("libraryDelete")) $("libraryDelete").addEventListener("click", deleteOpenVoyage);
if ($("libraryEditForm")) $("libraryEditForm").addEventListener("submit", askVoyageEdit);
if ($("homeGlanceLook")) $("homeGlanceLook").addEventListener("click", loadHomeGlance);
if ($("echoCheckRun")) $("echoCheckRun").addEventListener("click", loadEcho);
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
if ($("askBackApply")) $("askBackApply").addEventListener("click", applyAnswers);
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
loadStatus();

// --------------------------------------------------------------------------- //
// My use cases: the saved voyage library
// --------------------------------------------------------------------------- //

let openVoyage = null;
let pendingDiff = null;
let libraryEntries = [];

function libraryNote(parent, text) {
  return deskLine(parent, "p", "desk-note", text);
}

async function loadLibrary() {
  const list = $("libraryList");
  if (!list) return;
  if (!voyageSurfaceEnabled) {
    list.textContent = "";
    libraryNote(list, "The use-case library is a loopback-only surface and stays closed here.");
    return;
  }
  try {
    const response = await fetch("/api/voyages");
    const payload = await response.json();
    if (!response.ok || payload.ok !== true) {
      throw new Error(payload.detail || payload.error || `request failed (${response.status})`);
    }
    libraryEntries = payload.voyages || [];
    renderLibrary(libraryEntries);
  } catch (error) {
    list.textContent = "";
    libraryNote(list, `The library could not be read: ${error.message}`);
  }
}

function renderLibraryCards(list, entries) {
  for (const entry of entries) {
    const card = deskLine(list, "article", "library-card");
    card.setAttribute("role", "listitem");
    if (!entry.editable) card.dataset.shipped = "true";
    deskLine(card, "span", "library-kind", entry.editable ? "SAVED" : "SPECIALIST · READ-ONLY");
    if (entry.overrides_links) {
      const warning = deskLine(card, "p", "library-warning");
      deskLine(warning, "span", "warning-mark", "▲");
      deskLine(warning, "b", null, "This voyage overrides its links");
      if (entry.authority_reason) deskLine(warning, "small", null, entry.authority_reason);
    }
    if (entry.status === "pending_capability") {
      deskLine(
        card,
        "p",
        "library-pending",
        `Waiting for: ${entry.missing_capability}`
      );
    }
    deskLine(card, "b", null, entry.name);
    deskLine(card, "p", null, entry.description || "");
    if (entry.schedule) {
      deskLine(
        card,
        "small",
        "library-schedule",
        `Standing routine · ${entry.schedule.cadence} at ${entry.schedule.at}`
        + " · you install the task, NemoFold registers nothing"
      );
    }
    deskLine(card, "small", "library-steps-line", entry.workflows.join(" → "));
    const button = document.createElement("button");
    button.type = "button";
    button.className = entry.editable ? "card-open" : "card-open secondary";
    button.append(
      instrumentIcon("wheel"),
      entry.editable ? "Open" : "Copy to my use cases"
    );
    button.addEventListener("click", () =>
      entry.editable ? openLibraryEntry(entry.voyage_id) : copySpecialist(entry.voyage_id)
    );
    card.append(button);
  }
}

function tagLabel(tag) {
  return tag.replace(/-/g, " ");
}

function setLibraryTag(tag) {
  // Re-rendering replaces the chip that was just activated, so a keyboard user
  // would be dropped back to the top of the document. Put them back on the
  // chip they chose, but only if that is where they were.
  const cameFromChip = document.activeElement?.dataset?.tagFilter !== undefined;
  activeTag = tag;
  // The scene follows the filter: choosing the standing routines is what turns
  // the porthole into the echo sounder.
  updateVoyageScene();
  renderLibrary(libraryEntries);
  if (cameFromChip) {
    document.querySelector(`[data-tag-filter="${CSS.escape(tag)}"]`)?.focus();
  }
}

function renderLibraryFilter(entries) {
  const panel = $("libraryFilter");
  if (!panel) return;
  panel.textContent = "";
  // Only on the tabs where a topic is the point. The registry is non-thematic
  // and the overview shows everything someone kept.
  if (!(currentPage === "processes" && currentTab === "workflows")) return;
  const tags = [...new Set(entries.flatMap((entry) => entry.tags || []))].sort();
  if (!tags.length) return;
  for (const [tag, label] of [["", "All"], ...tags.map((tag) => [tag, tagLabel(tag)])]) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.dataset.tagFilter = tag;
    chip.textContent = label;
    chip.setAttribute("aria-pressed", String(tag === activeTag));
    chip.addEventListener("click", () => setLibraryTag(tag));
    panel.append(chip);
  }
}

function renderLibrary(entries) {
  const list = $("libraryList");
  list.textContent = "";
  renderLibraryFilter(entries);
  if (!entries.length) {
    libraryNote(list, "Nothing saved yet. Copy a specialist to start your own library.");
    return;
  }
  if (activeTag) {
    const matching = entries.filter((entry) => (entry.tags || []).includes(activeTag));
    if (!matching.length) {
      libraryNote(
        list,
        `No use case is tagged ${tagLabel(activeTag)} yet. `
        + "The others are still there - clear the filter to see them."
      );
      const clear = document.createElement("button");
      clear.type = "button";
      clear.className = "secondary";
      clear.textContent = "Show all use cases";
      clear.addEventListener("click", () => setLibraryTag(""));
      list.append(clear);
      return;
    }
    entries = matching;
  }
  const pending = entries.filter((entry) => entry.status === "pending_capability");
  const ready = entries.filter((entry) => entry.status !== "pending_capability");
  const readyGroup = deskLine(list, "div", "library-group");
  renderLibraryCards(readyGroup, ready);
  if (!pending.length) return;
  // A use case someone wanted but the product cannot serve yet is kept, and
  // kept visibly apart, so nobody mistakes it for something that would run.
  const waiting = deskLine(list, "div", "library-waiting");
  deskLine(waiting, "p", "kicker", "WAITING FOR A NEW INSTRUMENT");
  deskLine(
    waiting,
    "p",
    "desk-note",
    "These are saved on purpose. Each becomes runnable once the named instrument exists."
  );
  const group = deskLine(waiting, "div", "library-group");
  renderLibraryCards(group, pending);
}

async function copySpecialist(presetId) {
  const list = $("libraryList");
  try {
    const response = await fetch("/api/voyage-preset", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        preset_id: presetId,
        input_roots: lines($("deskRoots")?.value || $("inputRoots").value),
        output_dir: $("outputDir").value
      })
    });
    const payload = await response.json();
    if (!response.ok || payload.ok !== true) {
      throw new Error(payload.detail || payload.error || `request failed (${response.status})`);
    }
    await loadLibrary();
    await openLibraryEntry(payload.voyage.voyage_id);
  } catch (error) {
    libraryNote(list, `Not copied: ${error.message}`);
  }
}

async function openLibraryEntry(voyageId) {
  try {
    const response = await fetch(`/api/voyage?id=${encodeURIComponent(voyageId)}`);
    const payload = await response.json();
    if (!response.ok || payload.ok !== true) {
      throw new Error(payload.detail || payload.error || `request failed (${response.status})`);
    }
    const voyage = payload.voyage;
    openVoyage = {
      voyage_id: voyage.voyage_id,
      name: voyage.name,
      description: voyage.description || "",
      overrides_links: voyage.model_authority === "chain_wins",
      authority_reason: voyage.authority_reason || "",
      rights: voyage.rights || null,
      policy_refs: voyage.policy_refs || [],
      tags: voyage.tags || [],
      schedule: voyage.schedule || null,
      workflows: voyage.steps.map((step) => step.workflow),
      steps: voyage.steps
    };
    renderVoyageDetail();
  } catch (error) {
    libraryNote($("libraryList"), `Not opened: ${error.message}`);
  }
}

function renderVoyageDetail() {
  const panel = $("libraryDetail");
  if (!openVoyage) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  $("libraryDetailTitle").textContent = openVoyage.name;
  $("libraryDetailDescription").textContent = openVoyage.description || "";
  const banner = $("libraryDetailWarning");
  banner.textContent = "";
  banner.hidden = !openVoyage.overrides_links;
  if (openVoyage.overrides_links) {
    deskLine(banner, "span", "warning-mark", "▲");
    deskLine(banner, "b", null, "This voyage overrides its links");
    if (openVoyage.authority_reason) {
      deskLine(banner, "small", null, openVoyage.authority_reason);
    }
  }
  renderVoyageGovernance();
  renderEntryBinder();
  const list = $("librarySteps");
  list.textContent = "";
  openVoyage.workflows.forEach((workflow, index) => {
    const row = deskLine(list, "div", "library-step");
    row.setAttribute("role", "listitem");
    deskLine(row, "span", "library-step-order", `STEP ${index + 1}`);
    deskLine(row, "b", null, workflowCards[workflow]?.title || workflow);
    deskLine(row, "small", null, workflow);
    const controls = deskLine(row, "div", "library-step-controls");
    for (const [label, delta] of [["↑", -1], ["↓", 1]]) {
      const move = document.createElement("button");
      move.type = "button";
      move.className = "secondary";
      move.textContent = label;
      move.setAttribute("aria-label", `Move step ${index + 1} ${delta < 0 ? "up" : "down"}`);
      move.disabled = index + delta < 0 || index + delta >= openVoyage.workflows.length;
      move.addEventListener("click", () => moveVoyageStep(index, delta));
      controls.append(move);
    }
    const drop = document.createElement("button");
    drop.type = "button";
    drop.className = "secondary";
    drop.textContent = "Remove";
    drop.disabled = openVoyage.workflows.length < 2;
    drop.addEventListener("click", () => removeVoyageStep(index));
    controls.append(drop);
  });
}

function governanceRow(parent, label, value, warn = false) {
  const row = deskLine(parent, "div", warn ? "governance-row warn" : "governance-row");
  deskLine(row, "dt", null, label);
  deskLine(row, "dd", null, value);
  return row;
}

// Rights above draft_only mean this voyage may reach outward. That is a
// property worth reading before running it, so it is stated in words - the
// colour is decoration, the sentence is the badge.
function renderVoyageGovernance() {
  const panel = $("libraryGovernance");
  if (!panel) return;
  panel.textContent = "";
  const rights = openVoyage.rights || "draft_only";
  const inherited = openVoyage.rights ? "set on this voyage" : "default";
  governanceRow(
    panel,
    "Outbound rights",
    `${rights} (${inherited})`,
    rights !== "draft_only"
  );
  if (rights !== "draft_only") {
    governanceRow(
      panel,
      "What that means",
      "This voyage may send on your behalf once a delivery adapter exists. Until"
      + " then every step still stops at a draft.",
      true
    );
  }
  if (openVoyage.tags && openVoyage.tags.length) {
    governanceRow(panel, "Tags", openVoyage.tags.join(" · "));
  }
  if (openVoyage.schedule) {
    governanceRow(
      panel,
      "Standing routine",
      `${openVoyage.schedule.cadence} at ${openVoyage.schedule.at}`
      + " · you install the task; NemoFold registers nothing"
    );
  }
  const bound = knownPolicies.filter((policy) =>
    (policy.bindings || []).some((item) => item.voyage_id === openVoyage.voyage_id));
  const named = openVoyage.policy_refs || [];
  if (bound.length || named.length) {
    governanceRow(
      panel,
      "Policies",
      [...bound.map((policy) => policy.name), ...named].join(" · ")
    );
  }
}

function renderEntryBinder() {
  // The same binding, reachable from the side a person happens to be on. A rule
  // you can only attach from the register is a rule you attach less often than
  // you meant to.
  const panel = $("libraryBinder");
  if (!panel || !openVoyage) return;
  panel.textContent = "";
  if (!knownPolicies.length) {
    deskLine(panel, "small", null, "No policy or rule is written yet.");
    return;
  }
  deskLine(panel, "small", null, "Bind a rule to this voyage:");
  const select = document.createElement("select");
  select.setAttribute("aria-label", "Policy or rule to bind to this voyage");
  for (const policy of knownPolicies) {
    const option = document.createElement("option");
    option.value = policy.policy_id;
    option.textContent = `${policy.form}: ${policy.name}`;
    select.append(option);
  }
  const step = document.createElement("input");
  step.type = "number";
  step.min = "0";
  step.value = "0";
  step.setAttribute("aria-label", "Step number, 0 for the whole voyage");
  const bind = document.createElement("button");
  bind.type = "button";
  bind.className = "secondary";
  bind.textContent = "Bind";
  bind.addEventListener("click", async () => {
    const policy = knownPolicies.find((item) => item.policy_id === select.value);
    if (!policy) return;
    await bindPolicy(policy, openVoyage.voyage_id, Number(step.value) || 0, true);
    await loadGovernanceRegister();
    renderVoyageDetail();
  });
  panel.append(select, step, bind);
  deskLine(panel, "small", null, "Step 0 binds the whole voyage.");
}

function moveVoyageStep(index, delta) {
  const target = index + delta;
  const workflows = openVoyage.workflows;
  const steps = openVoyage.steps;
  [workflows[index], workflows[target]] = [workflows[target], workflows[index]];
  if (steps.length === workflows.length) {
    [steps[index], steps[target]] = [steps[target], steps[index]];
  }
  renderVoyageDetail();
}

function removeVoyageStep(index) {
  openVoyage.workflows.splice(index, 1);
  if (openVoyage.steps.length > index) openVoyage.steps.splice(index, 1);
  renderVoyageDetail();
}

async function saveOpenVoyage(steps, name) {
  const response = await fetch("/api/voyages", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      voyage_id: openVoyage.voyage_id,
      name: name || openVoyage.name,
      description: openVoyage.description || "",
      steps
    })
  });
  const payload = await response.json();
  if (!response.ok || payload.ok !== true) {
    throw new Error(payload.detail || payload.error || `request failed (${response.status})`);
  }
  return payload.voyage;
}

function adoptSavedVoyage(saved) {
  openVoyage.name = saved.name;
  openVoyage.workflows = saved.steps.map((step) => step.workflow);
  openVoyage.steps = saved.steps;
}

async function saveVoyageChanges() {
  const diff = $("libraryDiff");
  diff.textContent = "";
  try {
    adoptSavedVoyage(await saveOpenVoyage(openVoyage.steps));
    libraryNote(diff, "Saved. The library now holds this order.");
    renderVoyageDetail();
    await loadLibrary();
  } catch (error) {
    libraryNote(diff, `Not saved: ${error.message}`);
  }
}

async function deleteOpenVoyage() {
  try {
    const response = await fetch("/api/voyage-delete", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({voyage_id: openVoyage.voyage_id})
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || payload.error || "not deleted");
    openVoyage = null;
    renderVoyageDetail();
    await loadLibrary();
  } catch (error) {
    libraryNote($("libraryDiff"), `Not deleted: ${error.message}`);
  }
}

// D-033: a quiet line when it worked, full step transparency when it did not.
function renderVoyageRun(result) {
  const panel = $("libraryRunResult");
  panel.textContent = "";
  const success = result.status === "executed";
  panel.dataset.mode = success ? "calm" : "explain";
  const artifacts = result.steps.reduce((total, step) => total + step.artifact_count, 0);
  if (result.run_level_override) {
    deskLine(
      panel,
      "p",
      "run-override-line",
      `Chosen for this run only: ${result.run_level_override}.`
      + " Each step below names the model it actually used."
    );
  }
  if (success) {
    deskLine(panel, "b", "run-calm", `Done · ${result.steps.length} step(s), ${artifacts} artifacts.`);
    const anchor = document.createElement("button");
    anchor.type = "button";
    anchor.className = "instrument-anchor section-anchor";
    anchor.setAttribute("aria-expanded", "false");
    anchor.setAttribute("aria-controls", "libraryRunDetail");
    anchor.dataset.collapse = "libraryRunDetail";
    anchor.append(instrumentIcon("lifebuoy"));
    deskLine(anchor, "span", null, "Show the steps, gates and models");
    deskLine(anchor, "i", "chevron");
    panel.append(anchor);
    // Editing is the normal move after a quality judgement, not only after a
    // failure, so it sits next to a successful run too.
    const refine = document.createElement("button");
    refine.type = "button";
    refine.className = "card-open secondary";
    refine.id = "libraryRefine";
    refine.append(instrumentIcon("wheel"), "Not happy? Insert or edit a step");
    refine.addEventListener("click", () => {
      $("libraryEditRequest").focus();
      $("libraryEditRequest").scrollIntoView({
        behavior: reducedMotionQuery?.matches ? "auto" : "smooth",
        block: "nearest"
      });
    });
    panel.append(refine);
  } else {
    deskLine(panel, "b", "run-explain",
      `Stopped at step ${result.stopped_at}. Later steps were not started.`);
  }
  const detail = deskLine(panel, "div", "collapse-panel run-detail");
  detail.id = "libraryRunDetail";
  detail.hidden = success;
  for (const step of result.steps) {
    const row = deskLine(detail, "div", "run-step");
    row.dataset.status = step.status;
    deskLine(row, "b", null, `Step ${step.order} · ${step.workflow} · ${step.status}`);
    deskLine(
      row,
      "small",
      null,
      `${step.artifact_count} artifact(s) · model ${step.model_used}`
        + ` (level: ${step.model_level}) · rights ${step.rights}`
    );
    deskLine(row, "small", "run-model-note", step.model_note);
    if (step.policy_note) deskLine(row, "small", "run-policy-note", step.policy_note);
    if (step.errors && step.errors.length) {
      deskLine(row, "small", "run-errors", step.errors.join(", "));
    }
  }
  if (!success) {
    libraryNote(panel,
      "Ask the captain below what is missing; a proposed change always arrives as a diff you confirm.");
  }
}

function runOverride() {
  const provider = $("libraryOverrideProvider")?.value || "";
  const model = ($("libraryOverrideModel")?.value || "").trim();
  if (!provider || !model) return null;
  return {provider, model};
}

async function runOpenVoyage() {
  const panel = $("libraryRunResult");
  panel.textContent = "";
  libraryNote(panel, "Running…");
  try {
    const override = runOverride();
    const request = {voyage_id: openVoyage.voyage_id};
    if (override) request.model_override = override;
    const response = await fetch("/api/voyage-run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(request)
    });
    const result = await response.json();
    if (result.steps === undefined) {
      throw new Error(result.detail || result.error || `request failed (${response.status})`);
    }
    renderVoyageRun(result);
  } catch (error) {
    panel.textContent = "";
    libraryNote(panel, `Not run: ${error.message}`);
  }
}

async function askVoyageEdit(event) {
  event?.preventDefault();
  const diff = $("libraryDiff");
  diff.textContent = "";
  const text = $("libraryEditRequest").value.trim();
  if (!text || !openVoyage) {
    libraryNote(diff, "Open a voyage and describe the change you want.");
    return;
  }
  try {
    const response = await fetch("/api/voyage-edit", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({voyage_id: openVoyage.voyage_id, text})
    });
    const edit = await response.json();
    if (!response.ok || edit.ok !== true) {
      throw new Error(edit.detail || edit.error || `request failed (${response.status})`);
    }
    renderVoyageDiff(edit);
  } catch (error) {
    libraryNote(diff, `No change proposed: ${error.message}`);
  }
}

function renderVoyageDiff(edit) {
  const panel = $("libraryDiff");
  panel.textContent = "";
  deskLine(panel, "span", "diff-action", `PROPOSED ${edit.action.toUpperCase()}`);
  deskLine(panel, "p", null, edit.summary);
  // The diff is computed against the saved voyage. If the panel holds unsaved
  // reordering, applying it would quietly discard that - so say it here rather
  // than let the two versions diverge without a word.
  const savedOrder = (edit.before || []).join(" ");
  if (openVoyage && openVoyage.workflows.join(" ") !== savedOrder) {
    libraryNote(
      panel,
      "This diff is based on the saved voyage. Your unsaved reordering is not part of "
      + "it - save the changes first if you want to keep that order."
    );
  }
  for (const note of edit.notes || []) deskLine(panel, "p", "desk-note", note);
  if (!edit.applicable || !edit.changed) {
    pendingDiff = null;
    return;
  }
  const table = deskLine(panel, "div", "diff-table");
  for (const pair of [["before", edit.before], ["after", edit.after]]) {
    const column = deskLine(table, "div", `diff-column diff-${pair[0]}`);
    deskLine(column, "span", null, pair[0].toUpperCase());
    const items = deskLine(column, "ol", null);
    for (const workflow of pair[1]) deskLine(items, "li", null, workflow);
  }
  pendingDiff = edit;
  const confirm = document.createElement("button");
  confirm.type = "button";
  confirm.id = "libraryDiffConfirm";
  confirm.className = "card-open";
  confirm.append(instrumentIcon("wheel"), "Apply this change");
  confirm.addEventListener("click", applyVoyageDiff);
  panel.append(confirm);
  deskLine(panel, "small", null,
    "Nothing changed yet. The library is written only when you apply.");
}

async function applyVoyageDiff() {
  if (!pendingDiff || !openVoyage) return;
  const diff = $("libraryDiff");
  try {
    const saved = await saveOpenVoyage(pendingDiff.steps_after, pendingDiff.new_name);
    adoptSavedVoyage(saved);
    pendingDiff = null;
    diff.textContent = "";
    libraryNote(diff, "Applied. The library now holds the changed voyage.");
    renderVoyageDetail();
    await loadLibrary();
  } catch (error) {
    libraryNote(diff, `Not applied: ${error.message}`);
  }
}
