# Document Services roadmap

NemoFold's twelve active workflow contracts remain the tested product baseline. The
services below are planned extensions of the same document theme. Existing skills and
BACH modules are reuse candidates, not proof that a service is already integrated.
Each item needs its own strict job parameters, provenance-preserving artifacts, safety
gates, license review, tests, and visible runtime status before it may be called active.

## Near-term document workflows

### DS01 — Synopsis Studio

Compare two or more approved documents and produce a source-grounded synopsis: common
positions, differences, contradictions, change matrix, strengths, missing evidence,
and a configurable synthesis structure. Every conclusion must retain document and
location references. Candidate foundation: `system-synopse`, Evidence Analyst, and
Version Resolver.

### DS02 — Bilingual Document Sync

Keep parallel language versions current under an explicit lead-language rule. Compare
section structure first, then claims, numbers, links, tables, changelogs, and invariant
code blocks. Permit a documented back-transfer when the secondary version fixes an
error or is demonstrably clearer. Candidate foundation: `bilingual-doc-sync`.

### DS03 — Rich Document Ingest

Turn mixed DOCX, XLSX, PPTX, PDF, MSG, EML, EPUB, image, and text collections into
structured, traceable input with an explicit extractor choice and fallback receipt.
Preserve headings and tables where the selected backend supports them; keep unsupported
or failed files visible. Candidate foundation: `dokument-ingest` and `doc-services`.

### DS04 — OCR and Scan Recovery

Detect whether a PDF already has a useful text layer, apply OCR only when necessary,
record engine and language, retain page coordinates and confidence where available,
and expose low-quality pages for review. Candidate foundation: `ocr_service` and the
existing PDF pipeline.

### DS05 — Document Privacy and Redaction Center

Extend outbound-context pseudonymization into inspectable whole-document detection,
redaction, reversible pseudonym profiles, and controlled de-anonymization. Keys and
reverse mappings remain local; no redacted export receives a green state without a
visual or structural verification receipt. Candidate foundation: `anonymizer_service`,
`privacy_classifier`, and `redaction_service`.

## Second-wave document workflows

### DS06 — Chunk and RAG Export

Export deterministic overlapping chunks with source IDs, offsets, token estimates,
hashes, and a manifest for external RAG systems or local knowledge bases. Chunk limits
must describe retrieval units rather than silently truncating the approved corpus.
Candidate foundation: `document-chunker` and NemoFold's local evidence index.

### DS07 — Dossier, Briefing, and Structured Report Workflows

Create research dossiers and evidence-backed briefings from approved documents, with
typed scaffolds for people, organizations, topics, and events. Add recurring specialist
reports such as funding reports only through explicit templates and claim validation.
Candidate foundation: `dossier-briefing`, `report_workflow_service`, and
`foerderbericht_pipeline`.

### DS08 — Template and Recurring Document Studio

Populate controlled Word templates, reusable report forms, letters, and serial
documents from verified fields while preserving style and exposing every substitution.
This is document production, distinct from the visual-brand work in UC10. Candidate
foundation: `word_template_service` and Artifact Studio.

### DS09 — Document QA, Revision, and Requirements Audit

Compare structure and content across revisions; validate headings, tables, numbers,
references, tracked changes, and selected Office-package invariants. A developer-doc
profile may compare documented requirements with code evidence. Candidate foundation:
`docs-analysis` and the existing DOCX/XLSX validators.

### DS10 — PDF Forms, Comments, and Controlled Edits

Inspect fillable fields, populate approved values, attach comments or annotations, and
verify bounding boxes and rendered output. Original files remain unchanged unless a
separate action plan is explicitly approved. Candidate foundation: the PDF form and
DOCX comment helpers in `doc-services`.

### DS11 — Duplicate and Near-Duplicate Review

Find exact hash duplicates and, later, explainable near-duplicate candidates. Results
form a review set; deletion or consolidation is never automatic and must use the normal
action journal. Candidate foundation: `dedup_scanner` and NemoFold inventory hashes.

### DS12 — Format Conversion and Publication Packages

Convert between approved document formats with source preservation, structural-loss
warnings, deterministic filenames, and open/validation checks. Publication packages
may combine final files, manifests, accessibility notes, and hashes. Candidate
foundation: `doc-services`, Storage Policies, and Artifact Studio.

## Separate design roadmap

UC10 Brief and Business Card Studio remains planned as a design-oriented product area.
It may reuse DS08's field and template contracts later, but it is not presented as a
document-processing workflow today.

## Activation gate

A roadmap service becomes active only when:

1. its user-facing outcome and non-goals are agreed;
2. imported code and dependencies pass provenance and license review;
3. the strict job schema rejects unknown settings and bounds every path;
4. originals, omissions, destructive actions, and external transfers remain visible;
5. representative fixtures, artifact hashes, and end-to-end tests pass; and
6. the web, CLI, API, and MCP surfaces report the same capability state.
