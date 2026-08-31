"""Captain's Desk planner: turns one plain-language request into prepared drafts.

The planner never runs anything. It reads a request, matches it against the
active workflow contracts, and returns an ordered plan whose steps are job
drafts a person still has to open, complete and execute. Everything it cannot
do today is named as such, with the closest honest approximation, because a
planner that quietly drops an intent is worse than one that says no.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .job_io import SUPPORTED_WORKFLOWS

VOYAGE_SCHEMA = "nemofold.voyage-plan.v1"
MAX_REQUEST_CHARS = 2_000
DEFAULT_OUTPUT_DIR = "run-reports/web-console"

# Data-flow order. Two matched workflows always appear in this sequence, so the
# same request yields the same plan regardless of the order words appeared in.
WORKFLOW_ORDER = {
    "smart_inbox": 10,
    "storage_policy": 20,
    "cleanup_rules": 30,
    "mail_to_case": 40,
    "folder_digest": 50,
    "version_resolver": 60,
    "contact_monitor": 70,
    "bundle_export": 80,
    "evidence_analyst": 90,
    "fact_distill": 92,
    "synopsis_merge": 94,
    "document_registry": 95,
    "report_studio": 100,
    "controlled_email": 110,
    "platform_proof": 120,
}

# Only these successors read the previous step's output instead of the approved
# source roots. Every other step keeps reading what the operator approved.
HANDOFFS = {
    "evidence_analyst": "bundle_export",
    "report_studio": "evidence_analyst",
}

WORKFLOW_TITLES = {
    "smart_inbox": "Smart Inbox",
    "storage_policy": "Storage Policies",
    "cleanup_rules": "Cleanup Rules",
    "mail_to_case": "Mail-to-Case",
    "controlled_email": "Controlled Email",
    "contact_monitor": "Contact Monitor",
    "bundle_export": "Bundle Export",
    "folder_digest": "Folder Digest",
    "evidence_analyst": "Evidence Analyst",
    "version_resolver": "Version Resolver",
    "report_studio": "Report Studio",
    "document_registry": "Document Registry",
    "fact_distill": "Fact Distill",
    "synopsis_merge": "Synopsis Merge",
    "platform_proof": "Platform Proof",
}

WORKFLOW_KEYWORDS: dict[str, tuple[str, ...]] = {
    "controlled_email": (
        "mail an", "email an", "e-mail an", "mail to", "email to", "write a mail",
        "schreib", "antworte", "antwort", "anschreiben", "reply", "draft a mail",
        "entwurf", "draft",
    ),
    "mail_to_case": (
        "eml", "posteingang", "mailordner", "mailbox", "korrespondenz", "mail case",
        "mail-to-case", "vorgang anlegen", "akte anlegen", "case anlegen",
    ),
    "smart_inbox": (
        "einsortier", "sortier", "einordn", "ablegen", "inbox", "sort ", "file them",
        "route new", "eingang aufräum",
    ),
    "storage_policy": (
        "benennung", "namensschema", "namenskonvention", "aufbewahr", "retention",
        "naming", "storage policy", "ablageregel", "archivier",
    ),
    "cleanup_rules": (
        "aufräum", "cleanup", "clean up", "bulk", "massenablage", "aufräumregel", "tidy",
    ),
    "bundle_export": (
        # "bündl" covers bündle/bündeln, "bündel" the noun; both spellings of the
        # umlaut are listed because people type either.
        "bündl", "bündel", "buendl", "buendel", "bundle", "zusammenstell", "paket",
        "export", "zip",
    ),
    "evidence_analyst": (
        "analysier", "analyze", "analyse", "beleg", "evidence", "zitat", "quote",
        # "widerspr" is the common stem of Widerspruch, Widersprüche and
        # widersprechen; the umlaut in the plural breaks a full-word match.
        "was steht", "widerspr", "conflict", "frage an", "beantworte",
        "extrahier", "extract",
    ),
    "folder_digest": (
        "überblick", "ueberblick", "digest", "geändert", "geaendert", "changed",
        "snapshot", "bestandsaufnahme", "was ist neu", "what changed",
        # "tagesbericht" belongs here, not with report_studio: a daily list of new
        # files with a short summary is exactly what the digest produces.
        "tagesbericht", "neue files", "neue dateien", "new files", "dazugekommen",
    ),
    "version_resolver": (
        "version", "fassung", "neuesten stand", "neueste stand", "aktuellste",
        "abgleich", "latest", "gültige", "gueltige", "up to date",
    ),
    "contact_monitor": (
        "zuständig", "zustaendig", "ansprechpartner", "kontakt", "contact",
        "responsib", "wer betreut",
    ),
    "report_studio": (
        "bericht", "report", "pdf", "docx", "odt", "ausdruck",
    ),
    "synopsis_merge": (
        "synopse", "synopsis", "zusammenführ", "zusammenfuehr", "zusammenfassen zu einem",
        "merge", "vergleiche die dokumente", "gegenüberstell", "gegenueberstell",
        "in ein dokument",
    ),
    "fact_distill": (
        "destillier", "distil", "fakten", "facts", "dubletten streichen",
        "doppeltes streichen", "entdoppel", "faktenauszug", "doppelt",
        "mehrfach vorkommend",
    ),
    "document_registry": (
        "verzeichnis", "register", "registry", "tabelle", "table", "übersichtstabelle",
        "spalten", "columns", "auflistung", "liste aller", "katalog", "erfasse",
        "strukturier", "in daten", "datenbank",
    ),
    "platform_proof": (
        "plattformnachweis", "platform proof",
    ),
}

RECURRENCE_KEYWORDS = (
    "regelmäßig", "regelmässig", "regelmaessig", "immer wenn", "jedes mal", "täglich",
    "taeglich", "wöchentlich", "woechentlich", "monatlich", "laufend", "automatisch",
    "recurring", "regularly", "daily", "weekly", "monthly", "every time", "schedule",
    "jeden tag", "jede woche", "jeden monat", "tagesbericht",
)


@dataclass(frozen=True, slots=True)
class RoadmapService:
    key: str
    label: str
    keywords: tuple[str, ...]
    reason: str
    alternative_workflows: tuple[str, ...]
    approximation: str


ROADMAP_SERVICES = (
    RoadmapService(
        key="bilingual_sync",
        label="Bilingual sync",
        keywords=("bilingual", "zweisprachig", "sprachversion", "übersetzung", "uebersetzung",
                  "translation"),
        reason=(
            "Bilingual sync is a planned Document Service. NemoFold cannot align two "
            "language versions of the same document today."
        ),
        alternative_workflows=("folder_digest", "version_resolver"),
        approximation=(
            "Today's approximation: keep both language files in one approved folder, take a "
            "Folder Digest snapshot to see which side changed, and let Version Resolver name "
            "the valid version and the changed lines. The comparison stays per file, not "
            "across languages."
        ),
    ),
    RoadmapService(
        key="ocr_rich_ingest",
        label="OCR and rich ingest",
        keywords=("ocr", "gescannt", "scan", "eingescannt", "bildinhalt", "handschrift"),
        reason=(
            "OCR and rich ingest are planned Document Services. Image content is not read; "
            "an image can be attached and hashed, but never quoted as evidence."
        ),
        alternative_workflows=(),
        approximation=(
            "Today's approximation: attach the image to the case or the draft, where it is "
            "recorded with its hash, and quote only from text-bearing sources."
        ),
    ),
    RoadmapService(
        key="redaction",
        label="Document redaction",
        keywords=("schwärz", "schwaerz", "redaction", "redigier", "unkenntlich"),
        reason=(
            "Document redaction is a planned Document Service. NemoFold pseudonymizes an "
            "outbound context package, but it does not produce a redacted document."
        ),
        alternative_workflows=(),
        approximation=(
            "Today's approximation: the privacy gate replaces sensitive strings in what "
            "leaves the host; the original file stays untouched and unredacted."
        ),
    ),
    RoadmapService(
        key="duplicate_review",
        label="Duplicate review",
        keywords=("duplikat", "dublette", "doppelte datei", "duplicate file",
                  "identische datei"),
        reason=(
            "Review of duplicate FILES is a planned Document Service. Repeated "
            "STATEMENTS are already handled: Fact Distill strikes them and lists every "
            "struck occurrence."
        ),
        alternative_workflows=("folder_digest",),
        approximation=(
            "Today's approximation: a Folder Digest lists every file with its hash, so "
            "identical files become visible without an automatic merge."
        ),
    ),
    RoadmapService(
        key="chat_delivery",
        label="Delivery through a chat service",
        keywords=("telegram", "whatsapp", "signal-nachricht", "slack", "messenger",
                  "per chat"),
        reason=(
            "NemoFold has no chat delivery. Sending through Telegram or any other "
            "messenger would need its own proven adapter, the same way email delivery "
            "does; announcing it before that adapter exists would be a claim, not a "
            "feature."
        ),
        alternative_workflows=("controlled_email",),
        approximation=(
            "Today's approximation: the finding is prepared as a Controlled Email draft "
            "with its approval digest, and you forward it from the app you already use."
        ),
    ),
    RoadmapService(
        key="uploader_attribution",
        label="Who put the file there",
        keywords=("einsteller", "hochgeladen von", "wer hat hochgeladen", "uploader",
                  "eingestellt von"),
        reason=(
            "Folder Digest records the file name, a short summary and the change state, "
            "but not the account that placed a file. Ownership attribution is a planned "
            "extension, and a guessed author would be worse than none."
        ),
        alternative_workflows=("folder_digest",),
        approximation=(
            "Today's approximation: the daily digest names every new file with its short "
            "content and its hash, which identifies the file even without an author."
        ),
    ),
    RoadmapService(
        key="rag_export",
        label="RAG export",
        keywords=("rag", "vektor", "embedding", "vector store"),
        reason="RAG export is a planned Document Service.",
        alternative_workflows=("bundle_export",),
        approximation=(
            "Today's approximation: Bundle Export writes a deterministic text bundle with "
            "manifest and hashes that a downstream system can ingest."
        ),
    ),
    RoadmapService(
        key="templates_forms_qa",
        label="Templates, forms and QA",
        keywords=("vorlage", "template", "formular", "pdf-formular", "qualitätssicherung",
                  "qualitaetssicherung"),
        reason="Templates, PDF forms and QA services are planned, not active.",
        alternative_workflows=(),
        approximation=(
            "Today's approximation: Report Studio renders a verified analysis into fixed "
            "formats; it does not fill or generate forms."
        ),
    ),
)

SEND_KEYWORDS = ("versend", "verschick", "abschick", "senden", "sende ", "send ", "send.",
                 "deliver", "raussschick", "rausschick")
ATTACHMENT_KEYWORDS = ("bild", "foto", "anhang", "attachment", "image", "photo", "beilage",
                       "screenshot")
OUTPUT_LOCATION_KEYWORDS = ("desktop", "schreibtisch", "arbeitsplatz", "downloads",
                            "dokumente ordner")


@dataclass(frozen=True, slots=True)
class VoyageStep:
    order: int
    workflow: str
    title: str
    why: str
    job: dict[str, Any]
    questions_to_user: tuple[str, ...] = ()
    reads_previous_step: bool = False


@dataclass(frozen=True, slots=True)
class UnavailableIntent:
    key: str
    label: str
    reason: str
    approximation: str
    alternative_workflows: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecurringNote:
    requested: bool
    message: str
    options: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VoyagePlan:
    request_text: str
    steps: tuple[VoyageStep, ...]
    unavailable: tuple[UnavailableIntent, ...]
    recurring: RecurringNote | None
    notes: tuple[str, ...] = field(default_factory=tuple)
    schema: str = VOYAGE_SCHEMA

    @property
    def matched(self) -> bool:
        return bool(self.steps or self.unavailable)


def _mentions(haystack: str, keyword: str) -> bool:
    """Match a keyword at a word start so German inflections still count."""
    return re.search(r"(?<!\w)" + re.escape(keyword), haystack) is not None


def _normalize(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("request text must be a string")
    stripped = text.strip()
    if not stripped:
        raise ValueError("request text must not be empty")
    if len(stripped) > MAX_REQUEST_CHARS:
        raise ValueError(f"request text exceeds {MAX_REQUEST_CHARS} characters")
    return stripped


def _step_output(output_dir: str, order: int, workflow: str) -> str:
    return f"{output_dir.rstrip('/')}/voyage/{order:02d}-{workflow}"


def _subject_seed(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:78]


def _job(
    workflow: str,
    *,
    input_roots: tuple[str, ...],
    output_dir: str,
    questions: tuple[str, ...] = (),
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "nemofold.job.v1",
        "workflow": workflow,
        "input_roots": list(input_roots),
        "target_roots": [],
        "output_dir": output_dir,
        "questions": list(questions),
        # The planner proposes; a person executes. Both gates stay at their
        # safe value no matter what the request asked for.
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "model_budget_usd": 0,
        "parameters": parameters or {},
    }


def _questions_for(workflow: str, text: str, roots_missing: bool) -> tuple[str, ...]:
    questions: list[str] = []
    if roots_missing:
        questions.append("Which approved folder should this step read?")
    if workflow == "controlled_email":
        questions.append("Which address should receive the draft?")
        questions.append("Which sender address should the draft carry?")
        if any(_mentions(text, item) for item in ATTACHMENT_KEYWORDS):
            questions.append(
                "Which approved file should be attached? It is attached and hashed, "
                "not read as evidence."
            )
    elif workflow == "mail_to_case":
        questions.append("Which case name should the dossier carry?")
    elif workflow == "evidence_analyst":
        questions.append("Which exact questions should be asked of the sources?")
    elif workflow == "smart_inbox":
        questions.append("Which target folder should the sorted files move into?")
    elif workflow == "document_registry":
        questions.append(
            "Which columns should the table carry, or which template fits "
            "(medical_reports, insurance_registry, recurring_costs)?"
        )
    elif workflow == "contact_monitor":
        questions.append(
            "Which earlier snapshot should the contacts be compared against, if any?"
        )
    if workflow in {
        "report_studio", "bundle_export", "fact_distill", "document_registry",
        "synopsis_merge",
    } and any(
        _mentions(text, keyword) for keyword in OUTPUT_LOCATION_KEYWORDS
    ):
        questions.append(
            "Which approved folder should receive the file? A desktop or downloads folder "
            "works only once it is one of the approved roots; NemoFold never writes "
            "outside them."
        )
    return tuple(questions)


def _why(workflow: str) -> str:
    return {
        "controlled_email": (
            "Writes the reply as a local RFC 822 draft with an approval digest. Nothing is "
            "sent: delivery needs a separately proven server adapter."
        ),
        "mail_to_case": (
            "Reads approved local .eml files into a source-grounded case dossier with a "
            "manifest and hash-recorded attachments."
        ),
        "smart_inbox": (
            "Plans an all-or-nothing move of new arrivals into approved folders, with a "
            "collision gate and an undo journal."
        ),
        "storage_policy": (
            "Resolves naming, format and retention rules into a reviewable plan before any "
            "file changes."
        ),
        "cleanup_rules": (
            "Routes what is already there and reports readable suggestions learned only "
            "from explicit corrections."
        ),
        "bundle_export": (
            "Builds one deterministic bundle with manifest and hashes, listing unreadable "
            "entries instead of hiding them."
        ),
        "evidence_analyst": (
            "Answers the questions against the approved sources and returns exact quotes "
            "with their locations and the gaps that remain."
        ),
        "folder_digest": (
            "Takes a snapshot of the folder so new, changed, unchanged and deleted files "
            "become visible."
        ),
        "version_resolver": (
            "Names which version is the valid one and compares the wording line by line."
        ),
        "contact_monitor": (
            "Surfaces who the sources say is responsible, with quotes, so a recipient is "
            "chosen from evidence rather than memory."
        ),
        "synopsis_merge": (
            "Folds the approved documents into one synopsis, keeps the source and line "
            "behind every paragraph, and shows disagreeing labels as conflict blocks "
            "instead of choosing a winner."
        ),
        "fact_distill": (
            "Lifts quotable facts out of every approved source and strikes repeated "
            "statements from the findings, listing each struck occurrence with the "
            "statement it repeats."
        ),
        "document_registry": (
            "Extracts the declared columns from every approved document into one table, "
            "with the source and line behind each filled cell and an empty cell wherever "
            "the sources say nothing."
        ),
        "report_studio": (
            "Renders one verified analysis into Markdown, TXT, PDF, DOCX and ODT without "
            "changing its claims."
        ),
        "platform_proof": (
            "Records a platform proof package; it never upgrades readiness into proof."
        ),
    }[workflow]


def _parameters_for(workflow: str, text: str) -> dict[str, Any]:
    if workflow == "controlled_email":
        return {
            "to": [],
            "cc": [],
            "subject": _subject_seed(text),
            "body": "",
            "attachment_source_ids": [],
            "send_requested": False,
        }
    if workflow == "mail_to_case":
        return {"case_id": "new-case", "include_attachments": True}
    if workflow == "folder_digest":
        return {"digest_depth": "full"}
    if workflow == "evidence_analyst":
        return {"analysis_mode": "local_extractive", "max_chunks": 64}
    wants_pdf = _mentions(text.casefold(), "pdf")
    if workflow == "synopsis_merge":
        return {"formats": ["pdf", "md"] if wants_pdf else ["md"]}
    if workflow == "fact_distill":
        return {
            "dedupe_scope": "normalized",
            "formats": ["pdf", "md"] if wants_pdf else ["md"],
            "focus_terms": [],
        }
    if workflow == "document_registry":
        return {
            "column_template": "medical_reports",
            "formats": ["pdf", "md"] if wants_pdf else ["md"],
            "topic_filter": [],
        }
    if workflow == "report_studio":
        # report_studio really renders PDF (report_studio.SUPPORTED_FORMATS), so a
        # request for a PDF is answered with the format, not with an apology.
        wants_pdf = _mentions(text.casefold(), "pdf")
        return {"formats": ["pdf", "md"] if wants_pdf else ["md"], "include_coverage": True}
    return {}


def _matched_workflows(haystack: str) -> set[str]:
    matched = set()
    for workflow, keywords in WORKFLOW_KEYWORDS.items():
        if workflow not in SUPPORTED_WORKFLOWS:
            continue
        if any(_mentions(haystack, keyword) for keyword in keywords):
            matched.add(workflow)
    return matched


def _matched_roadmap(haystack: str) -> list[RoadmapService]:
    return [
        service
        for service in ROADMAP_SERVICES
        if any(_mentions(haystack, keyword) for keyword in service.keywords)
    ]


def _recurring_note(haystack: str) -> RecurringNote | None:
    if not any(_mentions(haystack, keyword) for keyword in RECURRENCE_KEYWORDS):
        return None
    return RecurringNote(
        requested=True,
        message=(
            "NemoFold has no scheduler of its own and does not start itself. Repetition "
            "stays in your hands, in one of two honest ways."
        ),
        options=(
            "Run the prepared drafts again whenever you want a fresh result; each run "
            "keeps its own ledger, so the comparison stays traceable.",
            "Install a task in your own operating system that calls the NemoFold CLI with "
            "the exported job file. You install it, you can see it, and you can stop it.",
        ),
    )


def plan_voyage(
    text: str,
    *,
    input_roots: tuple[str, ...] | list[str] = (),
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> VoyagePlan:
    """Plan an ordered chain of job drafts for one plain-language request."""
    request = _normalize(text)
    haystack = request.casefold()
    roots = tuple(str(item).strip() for item in input_roots if str(item).strip())
    roots_missing = not roots

    workflows = _matched_workflows(haystack)
    roadmap = _matched_roadmap(haystack)
    for service in roadmap:
        workflows.update(service.alternative_workflows)

    notes: list[str] = []
    unavailable = [
        UnavailableIntent(
            key=service.key,
            label=service.label,
            reason=service.reason,
            approximation=service.approximation,
            alternative_workflows=service.alternative_workflows,
        )
        for service in roadmap
    ]
    if "controlled_email" in workflows and any(
        _mentions(haystack, keyword) for keyword in SEND_KEYWORDS
    ):
        unavailable.append(
            UnavailableIntent(
                key="mail_delivery",
                label="Sending the message",
                reason=(
                    "Actual delivery is blocked in this runtime. Controlled Email writes the "
                    "draft and an approval digest, and refuses to send until that exact "
                    "digest is confirmed and a server-side mail adapter is proven."
                ),
                approximation=(
                    "Today's approximation: the draft and its digest are prepared locally "
                    "and you send it from your own mail program."
                ),
                alternative_workflows=(),
            )
        )

    self_exporting = workflows & {"fact_distill", "document_registry", "synopsis_merge"}
    if self_exporting and "report_studio" in workflows and "evidence_analyst" not in workflows:
        # report_studio renders one verified analysis JSON, which these two do
        # not produce - and they already write every requested format themselves.
        workflows.discard("report_studio")
        notes.append(
            "The report formats are written by "
            + " and ".join(sorted(WORKFLOW_TITLES[item] for item in self_exporting))
            + " directly, so no separate Report Studio step is needed."
        )

    ordered = sorted(workflows, key=lambda item: WORKFLOW_ORDER[item])
    steps: list[VoyageStep] = []
    produced: dict[str, str] = {}
    for position, workflow in enumerate(ordered, start=1):
        step_output = _step_output(output_dir, position, workflow)
        source = HANDOFFS.get(workflow)
        reads_previous = source is not None and source in produced
        step_roots = (produced[source],) if source is not None and reads_previous else roots
        questions = _questions_for(workflow, haystack, roots_missing and not reads_previous)
        job = _job(
            workflow,
            input_roots=step_roots,
            output_dir=step_output,
            questions=(
                ("Which claims do the approved sources support?",)
                if workflow in {"evidence_analyst", "platform_proof"}
                else ()
            ),
            parameters=_parameters_for(workflow, request),
        )
        steps.append(
            VoyageStep(
                order=position,
                workflow=workflow,
                title=WORKFLOW_TITLES[workflow],
                why=_why(workflow),
                job=job,
                questions_to_user=questions,
                reads_previous_step=reads_previous,
            )
        )
        produced[workflow] = step_output

    if not steps and not unavailable:
        notes.append(
            "This request could not be matched to an active workflow. The active work areas "
            "are Document Center, Analysis Lab, Folder Routines, Artifact Studio and the "
            "Command Bridge; naming a document task in one of them usually resolves it."
        )
    elif not steps:
        notes.append(
            "Only planned services matched this request, so there is nothing to prepare yet."
        )
    if roots_missing and steps:
        notes.append(
            "No approved folder was named, so every step still asks for one. Drafts can be "
            "prepared once a root is chosen."
        )

    return VoyagePlan(
        request_text=request,
        steps=tuple(steps),
        unavailable=tuple(unavailable),
        recurring=_recurring_note(haystack),
        notes=tuple(notes),
    )


def plan_to_primitive(plan: VoyagePlan) -> dict[str, Any]:
    return {
        "schema": plan.schema,
        "request_text": plan.request_text,
        "matched": plan.matched,
        "steps": [
            {
                "order": step.order,
                "workflow": step.workflow,
                "title": step.title,
                "why": step.why,
                "job": step.job,
                "questions_to_user": list(step.questions_to_user),
                "reads_previous_step": step.reads_previous_step,
            }
            for step in plan.steps
        ],
        "unavailable": [
            {
                "key": item.key,
                "label": item.label,
                "reason": item.reason,
                "approximation": item.approximation,
                "alternative_workflows": list(item.alternative_workflows),
            }
            for item in plan.unavailable
        ],
        "recurring": (
            None
            if plan.recurring is None
            else {
                "requested": plan.recurring.requested,
                "message": plan.recurring.message,
                "options": list(plan.recurring.options),
            }
        ),
        "notes": list(plan.notes),
        "executed": False,
        "cloud_proof": False,
    }
