from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .acceptance_gates import (
    artifact_manifest_sha256,
    load_gate_register_template,
    verify_gate_evidence,
)
from .application import ExecutionConfig
from .artifacts import write_text_artifact
from .contracts import RunStatus, SourceRecord
from .document_index import DocumentIndex
from .inventory import _stable_source_id
from .ledger import RunLedger
from .voyage_runs import VoyageRunResult, run_voyage


class G03AcceptanceError(RuntimeError):
    """Raised when the executable G03 acceptance chain does not meet its contract."""


@dataclass(frozen=True, slots=True)
class G03AcceptanceBundle:
    root: Path
    register_path: Path
    positive_dossier_path: Path
    unreadable_dossier_path: Path
    unclassifiable_dossier_path: Path
    ambiguous_dossier_path: Path
    verification: dict[str, Any]


def run_g03_acceptance_bundle(
    output_root: str | Path,
) -> G03AcceptanceBundle:
    """Run the synthetic G03 positive and blocking paths and seal their evidence."""
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise G03AcceptanceError(f"g03_evidence_root_not_empty:{root}")
    root.mkdir(parents=True, exist_ok=True)
    positive_inputs = _write_positive_fixture(root)
    unreadable_input = _write_unreadable_fixture(root)
    unclassifiable_input = _write_unclassifiable_fixture(root)
    ambiguous_input = _write_ambiguous_fixture(root)
    config = ExecutionConfig(allowed_roots=(str(root),))

    positive = _run_positive_voyage(root, positive_inputs[0].parent, config)
    unreadable = _run_unreadable_voyage(root, unreadable_input.parent, config)
    unclassifiable = _run_unclassifiable_voyage(root, unclassifiable_input.parent, config)
    ambiguous = _run_ambiguous_voyage(root, ambiguous_input.parent, config)

    positive_report, output_artifacts = _verify_positive_result(root, positive)
    unreadable_report, unreadable_artifacts = _verify_unreadable_result(root, unreadable)
    unclassifiable_report, unclassifiable_artifacts = _verify_unclassifiable_result(
        root, unclassifiable
    )
    ambiguous_report, ambiguous_artifacts = _verify_ambiguous_result(root, ambiguous)

    handoff_path = root / "evidence" / "g03-handoff.json"
    handoff = positive.steps[-1].handoff
    if not isinstance(handoff, dict):
        raise G03AcceptanceError("g03_positive_handoff_missing")
    write_text_artifact(
        handoff_path,
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    input_artifacts = [
        _artifact_receipt(root, path)
        for path in (
            *positive_inputs,
            unreadable_input,
            unclassifiable_input,
            ambiguous_input,
        )
    ]
    dossier_artifacts = (
        Path(positive.dossier_path),
        Path(positive.dossier_path).with_suffix(".md"),
        Path(unreadable.dossier_path),
        Path(unreadable.dossier_path).with_suffix(".md"),
        Path(unclassifiable.dossier_path),
        Path(unclassifiable.dossier_path).with_suffix(".md"),
        Path(ambiguous.dossier_path),
        Path(ambiguous.dossier_path).with_suffix(".md"),
    )
    output_receipts = [
        _artifact_receipt(root, path)
        for path in (
            *output_artifacts,
            *unreadable_artifacts,
            *unclassifiable_artifacts,
            *ambiguous_artifacts,
            *dossier_artifacts,
        )
    ]
    receipt = {
        "run_id": positive.steps[-1].run_id,
        "input_sha256": artifact_manifest_sha256(input_artifacts),
        "output_sha256": artifact_manifest_sha256(output_receipts),
        "input_artifacts": input_artifacts,
        "output_artifacts": output_receipts,
        "handoff_receipts": [
            {
                "producer": "smart_inbox",
                "consumer": "folder_digest",
                "artifact_path": _relative(root, handoff_path),
                "artifact_sha256": _sha256(handoff_path),
                "status": "verified",
                "evidence": (
                    "Der verifizierte Aktionsplan mit Klassifikation und "
                    "Ablagerouten wurde hashgebunden an den Digest übergeben."
                ),
            }
        ],
        "run_report": {
            "path": _relative(root, positive_report),
            "sha256": _sha256(positive_report),
            "status": "executed",
            "verified": True,
        },
        "result_checks": [
            {
                "name": "intake_change_detection_and_classification",
                "passed": True,
                "evidence": (
                    "Neue und geänderte Dokumente im Eingang wurden erkannt und "
                    "deterministisch den Zielkategorien (Patient/Wissen) zugeordnet."
                ),
            },
            {
                "name": "deterministic_index_synchronization",
                "passed": True,
                "evidence": (
                    "Neue Quellen wurden angelegt, geänderte aktualisiert und "
                    "entfernte Dokumente aus dem Suchindex bereinigt."
                ),
            },
            {
                "name": "verified_action_plan_handoff",
                "passed": True,
                "evidence": (
                    "Der Consumer-Schritt übernahm ausschließlich den verifizierten "
                    "Aktionsplan ohne unzulässige Nebenwirkungen."
                ),
            },
        ],
        "negative_path": {
            "case": "unreadable_intake_document",
            "run_id": unreadable.steps[0].run_id,
            "status": "blocked",
            "blocked_as_expected": True,
            "evidence": (
                "Ein unlesbares Dokument im Posteingang stoppte die Ablage vor "
                "der Ausführung und erzeugte eine strukturierte Rückfrage."
            ),
            "run_report": {
                "path": _relative(root, unreadable_report),
                "sha256": _sha256(unreadable_report),
            },
        },
        "additional_negative_paths": [
            {
                "case": "unclassifiable_intake_document",
                "run_id": unclassifiable.steps[0].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "evidence": (
                    "Ein fachfremdes, nicht klassifizierbares Dokument blockierte "
                    "vor dem Einsortieren und forderte eine Nutzerzuordnung an."
                ),
                "run_report": {
                    "path": _relative(root, unclassifiable_report),
                    "sha256": _sha256(unclassifiable_report),
                },
            },
            {
                "case": "ambiguous_intake_document",
                "run_id": ambiguous.steps[0].run_id,
                "status": "blocked",
                "blocked_as_expected": True,
                "evidence": (
                    "Ein mehrdeutiges Dokument mit widerstreitenden Kategorienmerkmalen "
                    "blockierte vor der Ablage und forderte Klärung an."
                ),
                "run_report": {
                    "path": _relative(root, ambiguous_report),
                    "sha256": _sha256(ambiguous_report),
                },
            },
        ],
    }

    register = load_gate_register_template()
    gate = next(item for item in register["gates"] if item["gate_id"] == "G03")
    gate["status"] = "partial"
    gate["evidence"] = {
        "test_nodes": [],
        "run_receipts": [receipt],
    }
    verification = verify_gate_evidence(register, root)
    register_path = root / "gate-register.g03.json"
    write_text_artifact(
        register_path,
        json.dumps(register, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )
    return G03AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(positive.dossier_path),
        unreadable_dossier_path=Path(unreadable.dossier_path),
        unclassifiable_dossier_path=Path(unclassifiable.dossier_path),
        ambiguous_dossier_path=Path(ambiguous.dossier_path),
        verification=verification,
    )


def _write_positive_fixture(root: Path) -> tuple[Path, Path, Path]:
    inbox = root / "positive" / "inputs" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    targets_patient = root / "positive" / "targets" / "patient"
    targets_wissen = root / "positive" / "targets" / "wissen"
    targets_patient.mkdir(parents=True, exist_ok=True)
    targets_wissen.mkdir(parents=True, exist_ok=True)

    doc_patient = inbox / "01-patient-befund-mueller.txt"
    doc_patient.write_text(
        "Arztpraxis Dr. med. Weber - Innere Medizin\n"
        "Patient: Max Mueller\n"
        "Geburtsdatum: 1980-05-12\n"
        "Befund: Sonographie der Schilddruese ohne pathologischen Befund. "
        "Regelrechte Lage und normale Groesse beider Schilddruesenlappen.\n"
        "Diagnose: Euthyreote Struma nodosa Grad I.\n"
        "Therapieempfehlung: Verlaufskontrolle in 12 Monaten empfohlen.\n"
        "Behandelnder Arzt: Dr. med. Weber\n",
        encoding="utf-8",
    )

    doc_wissen = inbox / "02-fachwissen-leitlinie.txt"
    doc_wissen.write_text(
        "Klinische Leitlinie und Fachliteratur Endokrinologie\n"
        "Thema: Leitlinie zur Abklaerung von Schilddruesenknoten in der Primaerversorgung.\n"
        "Evidenzbasierte Medizin und klinische Studien zeigen signifikante "
        "Vorteile standardisierter Diagnostik.\n"
        "Forschungsergebnisse und Klassifikation nach TIRADS fuer die Schilddruese.\n"
        "Herausgeber: Deutsche Gesellschaft fuer Endokrinologie.\n",
        encoding="utf-8",
    )

    doc_update = inbox / "03-patient-verlauf-schmidt.txt"
    doc_update.write_text(
        "Gemeinschaftspraxis Dr. Fischer und Partner\n"
        "Patientin: Anna Schmidt\n"
        "Befund: Verlaufskontrolle nach medikamentoeser Therapie. Laborwerte im Normbereich.\n"
        "Diagnose: Morbus Basedow in Remission.\n"
        "Behandelnder Arzt: Dr. Fischer\n",
        encoding="utf-8",
    )

    # Pre-seed index to demonstrate update of changed source and pruning of removed source
    index_dir = root / "positive" / "output" / "smart_inbox" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    index = DocumentIndex(index_dir / "nemofold.sqlite3")
    source_id_03 = _stable_source_id("root-0/03-patient-verlauf-schmidt.txt")
    old_source = SourceRecord(
        source_id=source_id_03,
        path=str(doc_update.resolve()),
        display_name=doc_update.name,
        sha256="0000000000000000000000000000000000000000000000000000000000000000",
        mime_type="text/plain",
        extraction_status="unchanged",
    )
    index.index_source(old_source, "Anna Schmidt alter Befund vor der Behandlung")

    obsolete_source = SourceRecord(
        source_id="src_obsolete_draft",
        path=str((inbox / "obsolete-draft-2024.txt").resolve()),
        display_name="obsolete-draft-2024.txt",
        sha256="1111111111111111111111111111111111111111111111111111111111111111",
        mime_type="text/plain",
        extraction_status="unchanged",
    )
    index.index_source(obsolete_source, "Veraltetes Dokument das aus dem Bestand entfernt wurde")
    index.close()

    return doc_patient, doc_wissen, doc_update


def _write_unreadable_fixture(root: Path) -> Path:
    inbox = root / "unreadable" / "inputs" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    targets_patient = root / "unreadable" / "targets" / "patient"
    targets_wissen = root / "unreadable" / "targets" / "wissen"
    targets_patient.mkdir(parents=True, exist_ok=True)
    targets_wissen.mkdir(parents=True, exist_ok=True)
    corrupt = inbox / "01-scan-corrupt.txt"
    corrupt.write_bytes(b"BESCHAEDIGTER_SCAN_DATENSATZ\x00\x00\x00\x00\n")
    return corrupt


def _write_unclassifiable_fixture(root: Path) -> Path:
    inbox = root / "unclassifiable" / "inputs" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    targets_patient = root / "unclassifiable" / "targets" / "patient"
    targets_wissen = root / "unclassifiable" / "targets" / "wissen"
    targets_patient.mkdir(parents=True, exist_ok=True)
    targets_wissen.mkdir(parents=True, exist_ok=True)
    einkauf = inbox / "01-einkaufszettel.txt"
    einkauf.write_text(
        "Einkaufsliste fuer den Haushalt:\n"
        "Milch, Eier, Butter, Kaffee, Brot, Kaese, Mineralwasser.\n"
        "Bitte am Samstag im Supermarkt besorgen.\n",
        encoding="utf-8",
    )
    return einkauf


def _write_ambiguous_fixture(root: Path) -> Path:
    inbox = root / "ambiguous" / "inputs" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    targets_patient = root / "ambiguous" / "targets" / "patient"
    targets_wissen = root / "ambiguous" / "targets" / "wissen"
    targets_patient.mkdir(parents=True, exist_ok=True)
    targets_wissen.mkdir(parents=True, exist_ok=True)
    misch = inbox / "01-mischdokument.txt"
    misch.write_text(
        "Mischdokument Dokumentation:\n"
        "Patient Max Mueller mit Befund und Diagnose durch behandelnden Arzt.\n"
        "Fachliteratur und Leitlinie zur klinischen Studie der Forschung.\n",
        encoding="utf-8",
    )
    return misch


def _run_positive_voyage(
    root: Path,
    inbox: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    case = _g03_case(
        inbox,
        root / "positive" / "output",
        targets=[
            root / "positive" / "targets" / "patient",
            root / "positive" / "targets" / "wissen",
        ],
        voyage_id="g03_acceptance_positive",
        name="Dokumenteingang · Automatische Klassifikation und Index-Aktualisierung",
    )
    return run_voyage(
        case,
        config,
        run_id="g03_acceptance_positive",
        base_dir=root,
    )


def _run_unreadable_voyage(
    root: Path,
    inbox: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    case = _g03_case(
        inbox,
        root / "unreadable" / "output",
        targets=[
            root / "unreadable" / "targets" / "patient",
            root / "unreadable" / "targets" / "wissen",
        ],
        voyage_id="g03_acceptance_unreadable",
        name="Dokumenteingang · Unlesbare Eingabe blockiert",
    )
    return run_voyage(
        case,
        config,
        run_id="g03_acceptance_unreadable",
        base_dir=root,
    )


def _run_unclassifiable_voyage(
    root: Path,
    inbox: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    case = _g03_case(
        inbox,
        root / "unclassifiable" / "output",
        targets=[
            root / "unclassifiable" / "targets" / "patient",
            root / "unclassifiable" / "targets" / "wissen",
        ],
        voyage_id="g03_acceptance_unclassifiable",
        name="Dokumenteingang · Nicht klassifizierbare Eingabe blockiert",
    )
    return run_voyage(
        case,
        config,
        run_id="g03_acceptance_unclassifiable",
        base_dir=root,
    )


def _run_ambiguous_voyage(
    root: Path,
    inbox: Path,
    config: ExecutionConfig,
) -> VoyageRunResult:
    case = _g03_case(
        inbox,
        root / "ambiguous" / "output",
        targets=[
            root / "ambiguous" / "targets" / "patient",
            root / "ambiguous" / "targets" / "wissen",
        ],
        voyage_id="g03_acceptance_ambiguous",
        name="Dokumenteingang · Mehrdeutige Klassifikation blockiert",
    )
    return run_voyage(
        case,
        config,
        run_id="g03_acceptance_ambiguous",
        base_dir=root,
    )


def _g03_case(
    inbox: Path,
    output_root: Path,
    *,
    targets: list[Path],
    voyage_id: str,
    name: str,
) -> dict[str, Any]:
    return {
        "voyage_id": voyage_id,
        "name": name,
        "steps": [
            {
                "workflow": "smart_inbox",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "smart_inbox",
                    "input_roots": [str(inbox)],
                    "target_roots": [str(target) for target in targets],
                    "output_dir": str(output_root / "smart_inbox"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "classification_policy": "content_categories",
                        "confidence_threshold": 0.25,
                        "maintain_index": True,
                        "allowed_extensions": [".txt"],
                        "original_policy": "move",
                        "routes": [
                            {
                                "suffixes": [".txt"],
                                "target_root": 0,
                                "category": "patient",
                                "match_terms": ["Patient", "Befund", "Diagnose", "Arzt"],
                            },
                            {
                                "suffixes": [".txt"],
                                "target_root": 1,
                                "category": "wissen",
                                "match_terms": [
                                    "Fachliteratur",
                                    "Leitlinie",
                                    "Studie",
                                    "Forschung",
                                ],
                            },
                        ],
                    },
                },
            },
            {
                "workflow": "folder_digest",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(inbox)],
                    "output_dir": str(output_root / "digest"),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "summary_length": 3,
                        "digest_depth": "full",
                    },
                },
                "handoff": {
                    "format": "action-plan",
                },
            },
        ],
    }


def _verify_positive_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "executed" or len(result.steps) != 2:
        raise G03AcceptanceError("g03_positive_voyage_not_executed")
    handoff = result.steps[-1].handoff or {}
    if handoff.get("status") != "verified":
        raise G03AcceptanceError("g03_positive_handoff_not_verified")
    if handoff.get("producer_workflow") != "smart_inbox":
        raise G03AcceptanceError("g03_positive_producer_workflow_mismatch")
    if handoff.get("format") != "action-plan":
        raise G03AcceptanceError("g03_positive_handoff_format_mismatch")

    step_one_report = (
        Path(result.steps[0].output_dir) / "ledger" / f"{result.steps[0].run_id}.json"
    )
    step_two_report = (
        Path(result.steps[1].output_dir) / "ledger" / f"{result.steps[1].run_id}.json"
    )
    step_one_plan = (
        Path(result.steps[0].output_dir) / f"{result.steps[0].run_id}.action-plan.json"
    )
    step_one_manifest = (
        Path(result.steps[0].output_dir) / f"{result.steps[0].run_id}.index-manifest.json"
    )
    step_two_digest = (
        Path(result.steps[1].output_dir) / f"{result.steps[1].run_id}.digest.md"
    )

    for path in (
        step_one_report,
        step_two_report,
        step_one_plan,
        step_one_manifest,
        step_two_digest,
    ):
        if not path.is_file():
            raise G03AcceptanceError(f"g03_positive_artifact_missing:{path}")

    # Verify classification and index synchronization
    plan_payload = json.loads(step_one_plan.read_text(encoding="utf-8"))
    plans = plan_payload.get("plans", [])
    if len(plans) != 3:
        raise G03AcceptanceError("g03_positive_planned_count_mismatch")
    categories = {Path(item["source"]).name: item.get("category") for item in plans}
    if categories.get("01-patient-befund-mueller.txt") != "patient":
        raise G03AcceptanceError("g03_positive_category_mismatch:01")
    if categories.get("02-fachwissen-leitlinie.txt") != "wissen":
        raise G03AcceptanceError("g03_positive_category_mismatch:02")
    if categories.get("03-patient-verlauf-schmidt.txt") != "patient":
        raise G03AcceptanceError("g03_positive_category_mismatch:03")

    report_payload = json.loads(step_one_report.read_text(encoding="utf-8"))
    meta = report_payload.get("metadata", {})
    index_status = meta.get("index_status", {})
    pruned = meta.get("pruned_source_ids", [])
    if "src_obsolete_draft" not in pruned:
        raise G03AcceptanceError("g03_positive_pruned_source_missing")
    if not any(status == "indexed" for status in index_status.values()):
        raise G03AcceptanceError("g03_positive_indexed_status_missing")
    if not any(status == "updated" for status in index_status.values()):
        raise G03AcceptanceError("g03_positive_updated_status_missing")

    ledger = RunLedger(Path(result.steps[1].output_dir) / "ledger")
    consumer_report = ledger.load(result.steps[1].run_id)
    if consumer_report.status is not RunStatus.EXECUTED:
        raise G03AcceptanceError("g03_positive_consumer_not_executed")

    outputs = (
        step_one_report,
        step_one_plan,
        step_one_manifest,
        step_two_digest,
    )
    return step_two_report, outputs


def _verify_unreadable_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped" or result.stopped_at != 1:
        raise G03AcceptanceError("g03_unreadable_voyage_did_not_stop_at_step_one")
    step = result.steps[0]
    if step.status != "blocked":
        raise G03AcceptanceError("g03_unreadable_step_not_blocked")
    if not any("unreadable_input" in err for err in step.errors):
        raise G03AcceptanceError("g03_unreadable_missing_error")
    report = Path(step.output_dir) / "ledger" / f"{step.run_id}.json"
    plan = Path(step.output_dir) / f"{step.run_id}.action-plan.json"
    question = Path(step.output_dir) / f"{step.run_id}.needs-user-input.json"
    for path in (report, plan, question):
        if not path.is_file():
            raise G03AcceptanceError(f"g03_unreadable_artifact_missing:{path}")
    return report, (plan, question)


def _verify_unclassifiable_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped" or result.stopped_at != 1:
        raise G03AcceptanceError("g03_unclassifiable_voyage_did_not_stop_at_step_one")
    step = result.steps[0]
    if step.status != "blocked":
        raise G03AcceptanceError("g03_unclassifiable_step_not_blocked")
    if not any("unclassifiable_input" in err for err in step.errors):
        raise G03AcceptanceError("g03_unclassifiable_missing_error")
    report = Path(step.output_dir) / "ledger" / f"{step.run_id}.json"
    plan = Path(step.output_dir) / f"{step.run_id}.action-plan.json"
    question = Path(step.output_dir) / f"{step.run_id}.needs-user-input.json"
    for path in (report, plan, question):
        if not path.is_file():
            raise G03AcceptanceError(f"g03_unclassifiable_artifact_missing:{path}")
    return report, (plan, question)


def _verify_ambiguous_result(
    root: Path,
    result: VoyageRunResult,
) -> tuple[Path, tuple[Path, ...]]:
    if result.status != "stopped" or result.stopped_at != 1:
        raise G03AcceptanceError("g03_ambiguous_voyage_did_not_stop_at_step_one")
    step = result.steps[0]
    if step.status != "blocked":
        raise G03AcceptanceError("g03_ambiguous_step_not_blocked")
    if not any("ambiguous_classification" in err for err in step.errors):
        raise G03AcceptanceError("g03_ambiguous_missing_error")
    report = Path(step.output_dir) / "ledger" / f"{step.run_id}.json"
    plan = Path(step.output_dir) / f"{step.run_id}.action-plan.json"
    question = Path(step.output_dir) / f"{step.run_id}.needs-user-input.json"
    for path in (report, plan, question):
        if not path.is_file():
            raise G03AcceptanceError(f"g03_ambiguous_artifact_missing:{path}")
    return report, (plan, question)


def _artifact_receipt(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": _relative(root, path),
        "sha256": _sha256(path),
    }


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
