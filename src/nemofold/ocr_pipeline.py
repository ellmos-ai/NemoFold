"""OCR and Knowledge Index Pipeline (Gate G11, Ellmos UC 2, 16, 47).

Provides image and PDF scan detection, page-level OCR quality verification,
deterministic duplicate and delta indexation, and verified FTS5 retrieval probing.
Halts fail-closed with needs-user-input when OCR quality falls below threshold or
unverified raster scan pages lack required review.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import ArtifactRecord, write_text_artifact
from .completeness import Question, needs_input_payload
from .contracts import (
    Coverage,
    SourceRecord,
    WorkflowBlocked,
)
from .document_extract import (
    SourceHashMismatch,
    UnsupportedDocumentError,
    count_pdf_pages,
    extract_document_text,
    extract_pdf_pages,
    pdf_image_page_numbers,
)
from .document_index import DocumentIndex, SearchHit
from .evidence import compute_coverage
from .inventory import InventoryResult
from .pdf_page_expectations import PdfPageReview, _parse_page_review_map

OCR_GROUNDING_NOTICE = (
    "<!-- OCR- & Wissensindex-Prüfung: Textschichten und Bildseiten verifiziert. -->"
)
OCR_REVIEW_REQUIRED_NOTICE = (
    "<!-- Review-Hinweis: Bildbasierte Seiten mit niedriger Konfidenz "
    "erfordern manuelle Freigabe. -->"
)
DEFAULT_MIN_CONFIDENCE = 0.70


class OcrPipelineError(RuntimeError):
    """Raised when OCR pipeline verification encounters fatal invariant violations."""


@dataclass(frozen=True, slots=True)
class OcrPageResult:
    page: int
    method: str
    confidence: float
    text: str
    needs_review: bool
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "method": self.method,
            "confidence": round(self.confidence, 4),
            "needs_review": self.needs_review,
            "text_length": len(self.text),
            "text_sha256": hashlib.sha256(self.text.encode("utf-8")).hexdigest(),
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class DocumentOcrResult:
    source_id: str
    display_name: str
    sha256: str
    status: str
    total_pages: int
    ocr_pages: int
    native_pages: int
    mean_confidence: float
    pages: tuple[OcrPageResult, ...]
    extracted_text: str
    needs_review: bool
    review_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "display_name": self.display_name,
            "sha256": self.sha256,
            "status": self.status,
            "total_pages": self.total_pages,
            "ocr_pages": self.ocr_pages,
            "native_pages": self.native_pages,
            "mean_confidence": round(self.mean_confidence, 4),
            "needs_review": self.needs_review,
            "review_reason": self.review_reason,
            "pages": [p.as_dict() for p in self.pages],
        }


def assess_page_ocr(
    page_num: int,
    raw_text: str,
    has_raster_images: bool,
    expected_sha256: str,
    page_reviews: dict[int, PdfPageReview],
    min_confidence: float,
    synthetic_ocr_text: str | None = None,
    synthetic_confidence: float | None = None,
) -> OcrPageResult:
    """Assess OCR and text layer quality for a single document page."""
    clean_text = raw_text.strip()
    if page_num in page_reviews:
        review = page_reviews[page_num]
        if review.source_sha256 != expected_sha256:
            raise OcrPipelineError(
                f"page_review_sha_mismatch:page={page_num}:"
                f"expected={expected_sha256}:actual={review.source_sha256}"
            )
        reviewed_text = review.text.strip()
        review_conf = 0.98 if review.content_complete else 0.50
        needs_rev = review_conf < min_confidence
        return OcrPageResult(
            page=page_num,
            method=review.method,
            confidence=review_conf,
            text=reviewed_text,
            needs_review=needs_rev,
            notes=f"reviewed_by_{review.reviewer}",
        )

    if synthetic_ocr_text is not None:
        conf = (
            synthetic_confidence
            if synthetic_confidence is not None
            else 0.85
        )
        needs_rev = conf < min_confidence
        return OcrPageResult(
            page=page_num,
            method="ocr",
            confidence=conf,
            text=synthetic_ocr_text.strip(),
            needs_review=needs_rev,
            notes="synthetic_ocr_extraction" + ("_low_quality" if needs_rev else ""),
        )

    if clean_text and not has_raster_images:
        return OcrPageResult(
            page=page_num,
            method="native_text",
            confidence=1.0,
            text=clean_text,
            needs_review=False,
            notes="native_digital_text_layer",
        )

    if clean_text and has_raster_images:
        return OcrPageResult(
            page=page_num,
            method="native_text_with_images",
            confidence=0.95,
            text=clean_text,
            needs_review=False,
            notes="text_layer_present_with_embedded_images",
        )

    return OcrPageResult(
        page=page_num,
        method="unextracted_image",
        confidence=0.0,
        text="",
        needs_review=True,
        notes="raster_image_without_ocr_review",
    )


def process_document_ocr(
    source_record: SourceRecord,
    index: DocumentIndex,
    reviews_by_source: dict[str, dict[int, PdfPageReview]],
    min_confidence: float,
    synthetic_ocr_map: dict[str, tuple[str, float]],
    detect_duplicates: bool = True,
) -> DocumentOcrResult:
    """Process a single document through scan detection, OCR quality check, and delta index."""
    file_path = Path(source_record.path)
    suffix = file_path.suffix.lower()

    existing_hash = index.connection.execute(
        "SELECT source_id, display_name FROM sources WHERE sha256 = ?",
        (source_record.sha256,),
    ).fetchone()

    if detect_duplicates and existing_hash and existing_hash[0] != source_record.source_id:
        return DocumentOcrResult(
            source_id=source_record.source_id,
            display_name=source_record.display_name,
            sha256=source_record.sha256,
            status="duplicate_skipped",
            total_pages=1,
            ocr_pages=0,
            native_pages=1,
            mean_confidence=1.0,
            pages=(),
            extracted_text="",
            needs_review=False,
            review_reason=(
                f"Identical content already indexed under source {existing_hash[0]} "
                f"({existing_hash[1]})."
            ),
        )

    source_reviews = reviews_by_source.get(source_record.display_name, {})
    if not source_reviews:
        source_reviews = reviews_by_source.get(source_record.source_id, {})

    page_results: list[OcrPageResult] = []
    full_text_parts: list[str] = []

    if suffix == ".pdf":
        try:
            total_pages = count_pdf_pages(
                file_path, expected_sha256=source_record.sha256
            )
            raw_pages = extract_pdf_pages(
                file_path, expected_sha256=source_record.sha256
            )
            image_pages = set(
                pdf_image_page_numbers(
                    file_path, expected_sha256=source_record.sha256
                )
            )
        except (SourceHashMismatch, ValueError, UnsupportedDocumentError) as exc:
            raise OcrPipelineError(
                f"corrupted_or_unreadable_pdf:{source_record.display_name}:{exc}"
            ) from exc

        for p_num in range(1, total_pages + 1):
            p_text = raw_pages[p_num - 1] if p_num <= len(raw_pages) else ""
            has_img = p_num in image_pages
            synth_tuple = synthetic_ocr_map.get(
                f"{source_record.display_name}:{p_num}"
            )
            synth_text = synth_tuple[0] if synth_tuple else None
            synth_conf = synth_tuple[1] if synth_tuple else None

            res = assess_page_ocr(
                page_num=p_num,
                raw_text=p_text,
                has_raster_images=has_img,
                expected_sha256=source_record.sha256,
                page_reviews=source_reviews,
                min_confidence=min_confidence,
                synthetic_ocr_text=synth_text,
                synthetic_confidence=synth_conf,
            )
            page_results.append(res)
            if res.text:
                full_text_parts.append(res.text)
    else:
        try:
            doc_text = extract_document_text(
                file_path,
                expected_sha256=source_record.sha256,
            )
        except Exception as exc:
            raise OcrPipelineError(
                f"corrupted_or_unreadable_document:{source_record.display_name}:{exc}"
            ) from exc

        total_pages = 1
        res = OcrPageResult(
            page=1,
            method="native_text",
            confidence=1.0,
            text=doc_text,
            needs_review=False,
            notes="native_text_document",
        )
        page_results.append(res)
        full_text_parts.append(doc_text)

    needs_review = any(p.needs_review for p in page_results)
    review_reasons = [
        f"page_{p.page}_conf_{p.confidence:.2f}_{p.notes}"
        for p in page_results
        if p.needs_review
    ]

    total_conf = sum(p.confidence for p in page_results)
    mean_conf = total_conf / len(page_results) if page_results else 0.0
    ocr_pages_count = sum(1 for p in page_results if "ocr" in p.method)
    native_pages_count = sum(1 for p in page_results if "native" in p.method)
    combined_text = "\n\n".join(full_text_parts)

    status = "review_required" if needs_review else "indexed"

    if not needs_review and combined_text:
        existing_source = index.connection.execute(
            "SELECT sha256 FROM sources WHERE source_id = ?",
            (source_record.source_id,),
        ).fetchone()
        idx_res = index.index_source(source_record, combined_text)
        status = "updated" if (existing_source and idx_res == "updated") else "indexed"

    return DocumentOcrResult(
        source_id=source_record.source_id,
        display_name=source_record.display_name,
        sha256=source_record.sha256,
        status=status,
        total_pages=total_pages,
        ocr_pages=ocr_pages_count,
        native_pages=native_pages_count,
        mean_confidence=mean_conf,
        pages=tuple(page_results),
        extracted_text=combined_text,
        needs_review=needs_review,
        review_reason=", ".join(review_reasons),
    )


def execute_ocr_pipeline(
    job: Any,
    inventory: InventoryResult,
    run_id: str = "run",
) -> tuple[tuple[str, ...], tuple[ArtifactRecord, ...], Coverage, dict[str, Any]]:
    """Execute Gate G11 OCR and knowledge index pipeline under strict fail-closed contract."""
    parameters = getattr(job, "parameters", None) or {}
    output_dir = Path(getattr(job, "output_dir", "."))
    output_dir.mkdir(parents=True, exist_ok=True)
    min_confidence = float(parameters.get("min_confidence", DEFAULT_MIN_CONFIDENCE))
    detect_duplicates = bool(parameters.get("detect_duplicates", True))
    require_retrieval = bool(parameters.get("require_retrieval", True))
    test_query = parameters.get("test_query")
    if test_query is not None and not isinstance(test_query, str):
        raise ValueError("test_query must be a string")

    raw_reviews = parameters.get("page_reviews")
    reviews_by_source: dict[str, dict[int, PdfPageReview]] = {}
    if raw_reviews:
        parsed_reviews = _parse_page_review_map(
            raw_reviews,
            label="parameters.page_reviews",
            source_id_keys=False,
        )
        for src_name, rev_tuple in parsed_reviews.items():
            reviews_by_source[src_name] = {r.page: r for r in rev_tuple}

    synthetic_ocr_raw = parameters.get("synthetic_ocr_map", {})
    synthetic_ocr_map: dict[str, tuple[str, float]] = {}
    if isinstance(synthetic_ocr_raw, dict):
        for k, v in synthetic_ocr_raw.items():
            if isinstance(v, dict):
                synthetic_ocr_map[k] = (
                    str(v.get("text", "")),
                    float(v.get("confidence", 0.85)),
                )
            elif isinstance(v, (list, tuple)) and len(v) >= 2:
                synthetic_ocr_map[k] = (str(v[0]), float(v[1]))

    index_dir = output_dir / "index"
    index_path = index_dir / "nemofold.sqlite3"
    index = DocumentIndex(index_path)

    if not inventory.records:
        index.close()
        raise WorkflowBlocked(
            ("no_inventory_records_found_for_ocr",),
            actions=("ocr_pipeline", "intake_blocked"),
            coverage=compute_coverage(
                all_source_ids=(),
                read_source_ids=(),
                cited_source_ids=(),
            ),
        )

    results: list[DocumentOcrResult] = []
    read_sources: list[str] = []

    for rec in inventory.records:
        read_sources.append(rec.source_id)
        try:
            res = process_document_ocr(
                source_record=rec,
                index=index,
                reviews_by_source=reviews_by_source,
                min_confidence=min_confidence,
                synthetic_ocr_map=synthetic_ocr_map,
                detect_duplicates=detect_duplicates,
            )
            results.append(res)
        except OcrPipelineError as err:
            index.close()
            raise WorkflowBlocked(
                (f"ocr_pipeline_execution_error:{err}",),
                actions=("ocr_pipeline", "error_blocked"),
                coverage=compute_coverage(
                    all_source_ids=(r.source_id for r in inventory.records),
                    read_source_ids=tuple(read_sources),
                    cited_source_ids=(),
                ),
            ) from err

    review_needed_docs = [d for d in results if d.needs_review]
    if review_needed_docs:
        questions: list[Question] = []
        for doc in review_needed_docs:
            questions.append(
                Question(
                    field=f"ocr_review_{doc.source_id}",
                    prompt=(
                        f"Dokument '{doc.display_name}' enthält unzureichende oder "
                        f"ungeprüfte Bildseiten ({doc.review_reason}). Bitte führen "
                        "Sie einen OCR-Durchlauf durch oder bestätigen Sie die "
                        "Textextraktion manuell."
                    ),
                    why="Niedrige OCR-Qualität darf nicht still als vollständig indexiert gelten.",
                    kind="text",
                )
            )

        payload = needs_input_payload(tuple(questions), workflow="ocr_pipeline")
        needs_art = write_text_artifact(
            output_dir / f"{run_id}.needs-user-input.json",
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            "needs-user-input",
        )
        index.close()
        raise WorkflowBlocked(
            (
                f"low_ocr_quality_review_required:{len(review_needed_docs)}_documents",
                *(f"{d.display_name}:{d.review_reason}" for d in review_needed_docs),
            ),
            actions=("ocr_pipeline", "ocr_quality_check_blocked"),
            artifacts=(needs_art,),
            coverage=compute_coverage(
                all_source_ids=(r.source_id for r in inventory.records),
                read_source_ids=tuple(read_sources),
                cited_source_ids=(),
            ),
            metadata={
                "documents_requiring_review": len(review_needed_docs),
                "review_reasons": [d.review_reason for d in review_needed_docs],
            },
        )

    retrieval_hits: list[SearchHit] = []
    if test_query:
        retrieval_hits = list(index.search(test_query, limit=10))
        if require_retrieval and not retrieval_hits:
            index.close()
            raise WorkflowBlocked(
                (f"retrieval_probe_no_hits:{test_query}",),
                actions=("ocr_pipeline", "retrieval_probe_blocked"),
                coverage=compute_coverage(
                    all_source_ids=(r.source_id for r in inventory.records),
                    read_source_ids=tuple(read_sources),
                    cited_source_ids=(),
                ),
            )

    index.close()

    indexed_count = sum(1 for r in results if r.status == "indexed")
    updated_count = sum(1 for r in results if r.status == "updated")
    duplicate_count = sum(1 for r in results if r.status == "duplicate_skipped")
    total_pages = sum(r.total_pages for r in results)
    ocr_pages_total = sum(r.ocr_pages for r in results)
    mean_conf_all = (
        sum(r.mean_confidence for r in results) / len(results) if results else 0.0
    )

    json_report = {
        "schema": "nemofold.ocr-pipeline.v1",
        "run_id": run_id,
        "index_file": str(index_path.relative_to(output_dir)).replace("\\", "/"),
        "total_documents": len(results),
        "indexed_documents": indexed_count,
        "updated_documents": updated_count,
        "duplicate_documents": duplicate_count,
        "total_pages": total_pages,
        "ocr_pages": ocr_pages_total,
        "mean_confidence": round(mean_conf_all, 4),
        "min_confidence_threshold": min_confidence,
        "retrieval_probe": {
            "query": test_query or "",
            "hits": len(retrieval_hits),
            "verified": len(retrieval_hits) > 0 if test_query else True,
            "hit_chunks": [h.chunk_id for h in retrieval_hits],
        },
        "documents": [r.as_dict() for r in results],
    }

    json_artifact = write_text_artifact(
        output_dir / f"{run_id}.ocr-pipeline.json",
        json.dumps(json_report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "json",
    )

    md_content = render_ocr_pipeline_markdown(json_report, retrieval_hits)
    md_artifact = write_text_artifact(
        output_dir / f"{run_id}.ocr-pipeline.md",
        md_content,
        "markdown",
    )

    artifacts = (json_artifact, md_artifact)

    handoff = {
        "schema": "nemofold.ocr-pipeline-handoff.v1",
        "producer": "ocr_pipeline",
        "run_id": run_id,
        "total_documents": len(results),
        "indexed_count": indexed_count,
        "updated_count": updated_count,
        "duplicate_count": duplicate_count,
        "mean_confidence": round(mean_conf_all, 4),
        "retrieval_verified": len(retrieval_hits) > 0 if test_query else True,
        "summary_markdown": md_content,
    }

    coverage = compute_coverage(
        all_source_ids=(r.source_id for r in inventory.records),
        read_source_ids=tuple(read_sources),
        cited_source_ids=tuple(r.source_id for r in results if r.status != "duplicate_skipped"),
    )

    actions = (
        "ocr_and_index_pipeline",
        "detect_scans",
        "update_knowledge_index",
    )

    metadata = {
        "total_documents": len(results),
        "indexed_count": indexed_count,
        "updated_count": updated_count,
        "duplicate_count": duplicate_count,
        "mean_confidence": round(mean_conf_all, 4),
        "retrieval_hits": len(retrieval_hits),
        "handoff": handoff,
    }

    return actions, tuple(artifacts), coverage, metadata


def render_ocr_pipeline_markdown(
    report: dict[str, Any],
    hits: list[SearchHit],
) -> str:
    """Render human-readable Markdown summary for OCR and knowledge index pipeline."""
    lines = [
        "# OCR- und Wissensindex-Pipeline",
        "",
        OCR_GROUNDING_NOTICE,
        "",
        f"- **Run ID**: `{report['run_id']}`",
        f"- **Dokumente gesamt**: `{report['total_documents']}`",
        f"- **Neu indexiert**: `{report['indexed_documents']}`",
        f"- **Aktualisiert**: `{report['updated_documents']}`",
        f"- **Dubletten übersprungen**: `{report['duplicate_documents']}`",
        f"- **Seiten gesamt**: `{report['total_pages']}` (davon OCR: `{report['ocr_pages']}`)",
        f"- **Mittlere Konfidenz**: `{report['mean_confidence'] * 100:.1f}%` "
        f"(Mindestschwelle: `{report['min_confidence_threshold'] * 100:.0f}%`)",
        "",
        "## Dokumenten-Status und OCR-Prüfung",
        "",
        "| Quelle | Status | Seiten | Native | OCR | Konfidenz | Prüfhinweis |",
        "|---|---|---|---|---|---|---|",
    ]

    for doc in report["documents"]:
        rev_text = doc["review_reason"] if doc["review_reason"] else "ok"
        lines.append(
            f"| `{doc['display_name']}` | `{doc['status']}` | {doc['total_pages']} | "
            f"{doc['native_pages']} | {doc['ocr_pages']} | {doc['mean_confidence'] * 100:.1f}% | "
            f"{rev_text} |"
        )

    lines.extend(
        [
            "",
            "## Verifizierte Abrufprobe (FTS5)",
            "",
        ]
    )

    probe = report["retrieval_probe"]
    if probe["query"]:
        mark = "BESTANDEN" if probe["verified"] else "NICHT BESTANDEN"
        lines.append(f"- **Suchbegriff**: `{probe['query']}`")
        lines.append(f"- **Ergebnis**: `[{mark}]` ({probe['hits']} Treffer)")
        lines.append("")
        if hits:
            lines.append("| Rang | Chunk-ID | Quelle | Textausschnitt |")
            lines.append("|---|---|---|---|")
            for idx, hit in enumerate(hits, start=1):
                clean_snippet = hit.text.replace("\n", " ")[:80]
                lines.append(
                    f"| {idx} | `{hit.chunk_id}` | `{hit.source_id}` | {clean_snippet}... |"
                )
    else:
        lines.append("*(Keine gesonderte Abrufprobe angefordert)*")

    lines.append("")
    return "\n".join(lines)
