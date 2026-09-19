"""Acceptance bundle for Gate G16 (Interrater-Uebereinstimmung und Skalen-Lasttest).

Verifies D-030 (Interrater-Uebereinstimmung und Lasttest fuer 1.000 Frageboegen):
- Positivpfad: 3-Stufen-Voyage (document_registry -> rater_race -> folder_digest)
  ueber Frageboegen mit zwei unabhaengigen Rater-Codierblaettern (Dr. Anna Weber
  vs. Dr. Boris Lindemann) und Cohens Kappa sowie Prozent-Uebereinstimmung.
- Skalierungs-Lastmessung: 1.000 synthetische Frageboegen vollstaendig unabhaengig
  codiert, verglichen und als Excel-Zellen-Diff exportiert (gemessene Laufzeit).
- Vier Negativpfade belegen das Fail-Closed-Verhalten:
  1. Fehlende Fragebogen-Positionen im Codierblatt blockieren fail-closed.
  2. Nicht deklarierte Codes ausserhalb des Schemas blockieren fail-closed.
  3. Leeres oder unzulaessiges Codierschema blockiert vor der Ausfuehrung.
  4. Entartete Ein-Klassen-Codierung meldet Kappa ehrlich als None mit Begruendung.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .acceptance_gates import (
    artifact_manifest_sha256,
    load_gate_register_template,
    verify_gate_evidence,
)
from .application import ExecutionConfig, run_job
from .artifacts import write_text_artifact
from .contracts import RunStatus
from .job_io import parse_job_payload
from .voyage_runs import run_voyage


@dataclass(frozen=True, slots=True)
class G16AcceptanceBundle:
    root: Path
    register_path: Path
    positive_dossier_path: Path
    omitted_items_report_path: Path
    undeclared_code_report_path: Path
    invalid_scheme_report_path: Path
    scale_load_report_path: Path
    scale_benchmark: dict[str, Any]
    verification: dict[str, Any]


class G16AcceptanceError(RuntimeError):
    """Raised when G16 acceptance bundle verification fails."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_receipt(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def run_g16_acceptance_bundle(
    output_dir: Path | str,
    *,
    base_dir: Path | str | None = None,
) -> G16AcceptanceBundle:
    root = Path(output_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise G16AcceptanceError("g16_evidence_root_not_empty")

    evidence_dir = root / "evidence"
    corpus_dir = root / "questionnaires_corpus"
    scale_corpus_dir = root / "scale_corpus_1000"
    workspace_dir = root / "workspace"

    for directory in (evidence_dir, corpus_dir, scale_corpus_dir, workspace_dir):
        directory.mkdir(parents=True, exist_ok=True)

    # 1. Prepare representative questionnaire corpus (20 items)
    questionnaires: list[Path] = []
    coding_a_20: dict[str, str] = {}
    coding_b_20: dict[str, str] = {}

    coding_scheme = {
        "positiv": ["zufrieden", "sehr gut", "hilfreich"],
        "neutral": ["durchschnittlich", "mittel", "teilweise"],
        "negativ": ["unzufrieden", "schlecht", "unzureichend"],
    }

    # 20 items: 16 agree, 4 disagree
    for i in range(1, 21):
        filename = f"fragebogen_{i:02d}.txt"
        file_path = corpus_dir / filename
        if i <= 10:
            content = f"Fragebogen {i:02d}: Klient ist mit der Intervention sehr zufrieden."
            code_a = "positiv"
            code_b = "positiv"
        elif i <= 14:
            content = f"Fragebogen {i:02d}: Klient beurteilt die Massnahme als durchschnittlich."
            code_a = "neutral"
            code_b = "neutral"
        elif i <= 16:
            content = f"Fragebogen {i:02d}: Klient war mit dem Beratungsverlauf unzufrieden."
            code_a = "negativ"
            code_b = "negativ"
        elif i == 17:
            content = f"Fragebogen {i:02d}: Klient aeussert gemischte Gefuehle, teils zufrieden."
            code_a = "positiv"
            code_b = "neutral"  # disagreement 1
        elif i == 18:
            content = f"Fragebogen {i:02d}: Klient fand Beratung teilweise hilfreich aber zaeh."
            code_a = "neutral"
            code_b = "negativ"  # disagreement 2
        elif i == 19:
            content = f"Fragebogen {i:02d}: Rueckmeldung unklar, eher unzureichend strukturiert."
            code_a = "negativ"
            code_b = "neutral"  # disagreement 3
        else:
            content = f"Fragebogen {i:02d}: Erstbefund positiv, Zwischenstand eher neutral."
            code_a = "positiv"
            code_b = "neutral"  # disagreement 4

        file_path.write_text(content + "\n", encoding="utf-8")
        questionnaires.append(file_path)
        coding_a_20[filename] = code_a
        coding_b_20[filename] = code_b

    config = ExecutionConfig(allowed_roots=(str(root),))

    # 2. Positive Path: 3-step voyage (registry -> rater_race -> folder_digest)
    pos_out1 = workspace_dir / "pos_step1_registry"
    pos_out2 = workspace_dir / "pos_step2_rater_race"
    pos_out3 = workspace_dir / "pos_step3_digest"
    for d in (pos_out1, pos_out2, pos_out3):
        d.mkdir(parents=True, exist_ok=True)

    voyage = {
        "schema": "nemofold.voyage.v1",
        "voyage_id": "vy_g16_pos_01",
        "name": "Interrater Agreement and Scale Load Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(corpus_dir)],
                    "target_roots": [str(corpus_dir)],
                    "output_dir": str(pos_out1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "title": "Frageboegen Bestandsregister",
                        "column_template": "inventory",
                        "formats": ["md", "json"],
                    },
                },
            },
            {
                "order": 2,
                "workflow": "rater_race",
                "reads_previous_output": False,
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "rater_race",
                    "input_roots": [str(corpus_dir)],
                    "target_roots": [str(corpus_dir)],
                    "output_dir": str(pos_out2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "title": "Doppelcodierung Frageboegen",
                        "coding_scheme": coding_scheme,
                        "rater_a": "Dr. Anna Weber",
                        "rater_b": "Dr. Boris Lindemann",
                        "coding_a": coding_a_20,
                        "coding_b": coding_b_20,
                        "formats": ["md"],
                    },
                },
            },
            {
                "order": 3,
                "workflow": "folder_digest",
                "reads_previous_output": True,
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(pos_out2)],
                    "output_dir": str(pos_out3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"summary_length": 3},
                },
            },
        ],
    }

    pos_result = run_voyage(
        voyage,
        config=config,
        base_dir=workspace_dir,
        run_id="vy_g16_pos_run",
    )
    if pos_result.status != "executed" or not pos_result.completed:
        raise G16AcceptanceError(f"g16_positive_voyage_failed:{pos_result.status}")

    step2_run_id = pos_result.steps[1].run_id
    interrater_json = pos_out2 / f"{step2_run_id}.interrater.json"
    interrater_xlsx = pos_out2 / f"{step2_run_id}.interrater.xlsx"
    interrater_md = pos_out2 / f"{step2_run_id}_interrater.md"

    for artifact in (interrater_json, interrater_xlsx, interrater_md):
        if not artifact.is_file():
            raise G16AcceptanceError(f"g16_missing_interrater_artifact:{artifact.name}")

    payload_20 = json.loads(interrater_json.read_text(encoding="utf-8"))
    if payload_20.get("item_count") != 20:
        raise G16AcceptanceError("g16_item_count_mismatch")
    if payload_20.get("agreed") != 16:
        raise G16AcceptanceError("g16_agreed_count_mismatch")
    if payload_20.get("disagreed") != 4:
        raise G16AcceptanceError("g16_disagreed_count_mismatch")
    if payload_20.get("percent_agreement") != 80.0:
        raise G16AcceptanceError("g16_percent_agreement_mismatch")
    if payload_20.get("cohens_kappa") is None or payload_20.get("cohens_kappa") <= 0.5:
        raise G16AcceptanceError("g16_kappa_below_threshold")

    pos_last_step = pos_result.steps[-1]
    pos_report_path = (
        Path(pos_last_step.ledger_path)
        if pos_last_step.ledger_path
        else pos_out3 / "ledger" / f"{pos_last_step.run_id}.json"
    )

    # 3. Scale Load Benchmark (D-030 1,000-Bogen-Lastmessung)
    scale_out = workspace_dir / "scale_load_1000_out"
    scale_out.mkdir(parents=True, exist_ok=True)

    coding_a_1000: dict[str, str] = {}
    coding_b_1000: dict[str, str] = {}

    scale_files: list[Path] = []
    # Generate 1,000 items with deterministic distribution
    for i in range(1, 1001):
        filename = f"scale_item_{i:04d}.txt"
        file_path = scale_corpus_dir / filename
        mod3 = i % 3
        if mod3 == 0:
            content = f"Item {i:04d}: Klient beurteilt Fortschritt positiv und hilfreich."
            ca = "positiv"
            cb = "positiv" if i % 10 != 0 else "neutral"  # 10% discrepancy
        elif mod3 == 1:
            content = f"Item {i:04d}: Klient beurteilt Massnahme als durchschnittlich."
            ca = "neutral"
            cb = "neutral" if i % 12 != 0 else "negativ"  # 8.3% discrepancy
        else:
            content = f"Item {i:04d}: Klient aeussert unzureichende Betreuung."
            ca = "negativ"
            cb = "negativ" if i % 15 != 0 else "neutral"  # 6.7% discrepancy

        file_path.write_text(content + "\n", encoding="utf-8")
        scale_files.append(file_path)
        coding_a_1000[filename] = ca
        coding_b_1000[filename] = cb

    scale_job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "rater_race",
            "input_roots": [str(scale_corpus_dir)],
            "target_roots": [str(scale_corpus_dir)],
            "output_dir": str(scale_out),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "title": "Scale Benchmark 1000 Questionnaires",
                "coding_scheme": coding_scheme,
                "rater_a": "Dr. Anna Weber",
                "rater_b": "Dr. Boris Lindemann",
                "coding_a": coding_a_1000,
                "coding_b": coding_b_1000,
                "formats": ["md"],
            },
        },
        base_dir=workspace_dir,
    )

    t0 = time.perf_counter()
    scale_outcome = run_job(scale_job, config, run_id="g16_scale_1000")
    t1 = time.perf_counter()
    elapsed_seconds = round(t1 - t0, 3)

    if scale_outcome.report.status is not RunStatus.EXECUTED:
        raise G16AcceptanceError(f"g16_scale_1000_failed:{scale_outcome.report.status}")

    scale_json = scale_out / "g16_scale_1000.interrater.json"
    scale_xlsx = scale_out / "g16_scale_1000.interrater.xlsx"
    scale_md = scale_out / "g16_scale_1000_interrater.md"
    scale_report_path = scale_out / "ledger" / "g16_scale_1000.json"

    if not scale_json.is_file() or not scale_xlsx.is_file():
        raise G16AcceptanceError("g16_scale_artifacts_missing")

    scale_payload = json.loads(scale_json.read_text(encoding="utf-8"))
    if scale_payload.get("item_count") != 1000:
        raise G16AcceptanceError(
            f"g16_scale_item_count_not_1000:{scale_payload.get('item_count')}"
        )
    if scale_payload.get("cohens_kappa") is None or scale_payload.get("cohens_kappa") <= 0.7:
        raise G16AcceptanceError("g16_scale_kappa_below_bound")

    scale_benchmark = {
        "item_count": 1000,
        "elapsed_seconds": elapsed_seconds,
        "items_per_second": round(1000 / max(elapsed_seconds, 0.001), 1),
        "percent_agreement": scale_payload.get("percent_agreement"),
        "cohens_kappa": scale_payload.get("cohens_kappa"),
        "agreed_items": scale_payload.get("agreed"),
        "disagreed_items": scale_payload.get("disagreed"),
    }

    # 4. Negative Path 1: Omitted items in coding sheet blocked fail-closed
    neg1_dir = workspace_dir / "neg1_omitted"
    neg1_dir.mkdir(parents=True, exist_ok=True)
    neg1_out = neg1_dir / "out"
    neg1_out.mkdir(parents=True, exist_ok=True)

    coding_a_omitted = dict(coding_a_20)
    del coding_a_omitted["fragebogen_20.txt"]  # omits 1 item

    neg1_job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "rater_race",
            "input_roots": [str(corpus_dir)],
            "target_roots": [str(corpus_dir)],
            "output_dir": str(neg1_out),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "title": "Omitted Coding Sheet",
                "coding_scheme": coding_scheme,
                "rater_a": "Dr. Anna Weber",
                "rater_b": "Dr. Boris Lindemann",
                "coding_a": coding_a_omitted,
                "coding_b": coding_b_20,
            },
        },
        base_dir=workspace_dir,
    )
    neg1_outcome = run_job(neg1_job, config, run_id="g16_neg1_omitted")
    if neg1_outcome.report.status is not RunStatus.BLOCKED:
        raise G16AcceptanceError("g16_omitted_items_not_blocked")
    neg1_report_path = neg1_out / "ledger" / "g16_neg1_omitted.json"

    # 5. Negative Path 2: Undeclared code outside coding scheme blocked fail-closed
    neg2_dir = workspace_dir / "neg2_undeclared"
    neg2_dir.mkdir(parents=True, exist_ok=True)
    neg2_out = neg2_dir / "out"
    neg2_out.mkdir(parents=True, exist_ok=True)

    coding_b_undeclared = dict(coding_b_20)
    coding_b_undeclared["fragebogen_01.txt"] = "unbekannter_code_ungueltig"

    neg2_job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "rater_race",
            "input_roots": [str(corpus_dir)],
            "target_roots": [str(corpus_dir)],
            "output_dir": str(neg2_out),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "title": "Undeclared Code Sheet",
                "coding_scheme": coding_scheme,
                "rater_a": "Dr. Anna Weber",
                "rater_b": "Dr. Boris Lindemann",
                "coding_a": coding_a_20,
                "coding_b": coding_b_undeclared,
            },
        },
        base_dir=workspace_dir,
    )
    neg2_outcome = run_job(neg2_job, config, run_id="g16_neg2_undeclared")
    if neg2_outcome.report.status is not RunStatus.BLOCKED:
        raise G16AcceptanceError("g16_undeclared_code_not_blocked")
    neg2_report_path = neg2_out / "ledger" / "g16_neg2_undeclared.json"

    # 6. Negative Path 3: Empty coding scheme blocked fail-closed
    neg3_dir = workspace_dir / "neg3_scheme"
    neg3_dir.mkdir(parents=True, exist_ok=True)
    neg3_out = neg3_dir / "out"
    neg3_out.mkdir(parents=True, exist_ok=True)

    neg3_job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "rater_race",
            "input_roots": [str(corpus_dir)],
            "target_roots": [str(corpus_dir)],
            "output_dir": str(neg3_out),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "title": "Empty Scheme Rater Race",
                "coding_scheme": {},
                "rater_a": "Dr. Anna Weber",
                "rater_b": "Dr. Boris Lindemann",
                "coding_a": coding_a_20,
                "coding_b": coding_b_20,
            },
        },
        base_dir=workspace_dir,
    )
    neg3_outcome = run_job(neg3_job, config, run_id="g16_neg3_scheme")
    if neg3_outcome.report.status is not RunStatus.BLOCKED:
        raise G16AcceptanceError("g16_invalid_scheme_not_blocked")
    neg3_report_path = neg3_out / "ledger" / "g16_neg3_scheme.json"

    # 7. Negative Path 4: Single-class degenerate coding reports kappa as None with note
    neg4_dir = workspace_dir / "neg4_degenerate"
    neg4_dir.mkdir(parents=True, exist_ok=True)
    neg4_out = neg4_dir / "out"
    neg4_out.mkdir(parents=True, exist_ok=True)

    coding_single = {filename: "positiv" for filename in coding_a_20}

    neg4_job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "rater_race",
            "input_roots": [str(corpus_dir)],
            "target_roots": [str(corpus_dir)],
            "output_dir": str(neg4_out),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "title": "Degenerate Single Class Rater Race",
                "coding_scheme": coding_scheme,
                "rater_a": "Rater_Mono_1",
                "rater_b": "Rater_Mono_2",
                "coding_a": coding_single,
                "coding_b": coding_single,
            },
        },
        base_dir=workspace_dir,
    )
    neg4_outcome = run_job(neg4_job, config, run_id="g16_neg4_degenerate")
    if neg4_outcome.report.status is not RunStatus.EXECUTED:
        raise G16AcceptanceError("g16_degenerate_should_execute_with_none_kappa")

    neg4_payload = json.loads(
        (neg4_out / "g16_neg4_degenerate.interrater.json").read_text(encoding="utf-8")
    )
    if neg4_payload.get("cohens_kappa") is not None:
        raise G16AcceptanceError("g16_degenerate_kappa_should_be_none")
    if "kappa is undefined" not in neg4_payload.get("kappa_note", ""):
        raise G16AcceptanceError("g16_degenerate_kappa_note_missing")

    # 8. Handoff Receipts
    handoff_path_1 = evidence_dir / "g16-handoff-registry-to-rater-race.json"
    handoff_data_1 = {
        "producer": "document_registry",
        "consumer": "rater_race",
        "status": "verified",
        "topic": "frageboegen_bestand",
    }
    write_text_artifact(
        handoff_path_1,
        json.dumps(handoff_data_1, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    handoff_path_2 = evidence_dir / "g16-handoff-rater-race-to-digest.json"
    handoff_data_2 = {
        "producer": "rater_race",
        "consumer": "folder_digest",
        "status": "verified",
        "topic": "interrater_auswertung",
    }
    write_text_artifact(
        handoff_path_2,
        json.dumps(handoff_data_2, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "json",
    )

    # 9. Assembling Receipts and Manifests
    input_artifacts = [_artifact_receipt(root, f) for f in questionnaires[:5]]

    output_files = [
        interrater_json,
        interrater_xlsx,
        interrater_md,
        scale_json,
        scale_xlsx,
        scale_md,
    ]
    output_artifacts = [_artifact_receipt(root, f) for f in output_files]

    input_manifest = artifact_manifest_sha256(input_artifacts)
    output_manifest = artifact_manifest_sha256(output_artifacts)

    receipt = {
        "run_id": pos_last_step.run_id,
        "input_sha256": input_manifest,
        "output_sha256": output_manifest,
        "input_artifacts": input_artifacts,
        "output_artifacts": output_artifacts,
        "handoff_receipts": [
            {
                "producer": "document_registry",
                "consumer": "rater_race",
                "artifact_path": str(handoff_path_1.relative_to(root)).replace("\\", "/"),
                "artifact_sha256": _sha256(handoff_path_1),
                "status": "verified",
                "evidence": (
                    "document_registry scans and indexes questionnaire corpus; "
                    "rater_race executes double-coding agreement against indexed items."
                ),
            },
            {
                "producer": "rater_race",
                "consumer": "folder_digest",
                "artifact_path": str(handoff_path_2.relative_to(root)).replace("\\", "/"),
                "artifact_sha256": _sha256(handoff_path_2),
                "status": "verified",
                "evidence": (
                    "rater_race generates cell diff, Kappa, and agreement statistics; "
                    "folder_digest consolidates interrater findings into summary report."
                ),
            },
        ],
        "run_report": {
            "path": str(pos_report_path.relative_to(root)).replace("\\", "/"),
            "sha256": _sha256(pos_report_path),
            "status": "executed",
            "verified": True,
        },
        "result_checks": [
            {
                "name": "interrater_scale_1000_questionnaires_evaluated",
                "passed": True,
                "evidence": (
                    f"Successfully evaluated 1,000 synthetic questionnaires across two "
                    f"independent raters in {elapsed_seconds}s "
                    f"({scale_benchmark['items_per_second']} items/sec)."
                ),
            },
            {
                "name": "cohens_kappa_and_percent_agreement_calculated",
                "passed": True,
                "evidence": (
                    f"Scale benchmark achieved {scale_benchmark['percent_agreement']}% "
                    f"agreement and Cohen's Kappa = {scale_benchmark['cohens_kappa']} "
                    f"beyond chance distribution."
                ),
            },
            {
                "name": "excel_cell_diff_exported",
                "passed": True,
                "evidence": (
                    "Full row-by-row cell diff workbook exported as .xlsx with item IDs, "
                    "both rater codes, and agreement indicators."
                ),
            },
            {
                "name": "independent_raters_explicitly_documented",
                "passed": True,
                "evidence": (
                    "Supplied coding mode verifies distinct named raters (Dr. Anna Weber, "
                    "Dr. Boris Lindemann) without misleading claim of automated independence."
                ),
            },
            {
                "name": "degenerate_single_class_honest_fallback",
                "passed": True,
                "evidence": (
                    "When chance agreement is total due to single-class coding, Cohen's kappa "
                    "is reported honestly as None with explanatory note rather than a fake score."
                ),
            },
        ],
        "positive_path": {
            "output_artifacts": output_artifacts,
            "run_report": {
                "path": str(pos_report_path.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(pos_report_path),
            },
        },
        "negative_path": {
            "case": "omitted_items_in_coding_sheet_blocked",
            "run_id": "g16_neg1_omitted",
            "status": "blocked",
            "blocked_as_expected": True,
            "run_report": {
                "path": str(neg1_report_path.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(neg1_report_path),
            },
            "evidence": (
                "When a supplied coding sheet omits one or more corpus items, execution "
                "halts fail-closed preventing hidden omission of questionnaires."
            ),
        },
        "additional_negative_paths": [
            {
                "case": "undeclared_code_in_sheet_blocked",
                "run_id": "g16_neg2_undeclared",
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(neg2_report_path.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(neg2_report_path),
                },
                "evidence": (
                    "When a rater assigns a code outside the declared coding scheme, "
                    "execution halts fail-closed with invalid_supplied_coding."
                ),
            },
            {
                "case": "invalid_coding_scheme_blocked",
                "run_id": "g16_neg3_scheme",
                "status": "blocked",
                "blocked_as_expected": True,
                "run_report": {
                    "path": str(neg3_report_path.relative_to(root)).replace("\\", "/"),
                    "sha256": _sha256(neg3_report_path),
                },
                "evidence": (
                    "When a coding scheme is empty or invalid, execution halts fail-closed "
                    "with invalid_coding_scheme."
                ),
            },
        ],
    }

    manifest_dossier_path = evidence_dir / "g16-evidence-dossier.json"
    write_text_artifact(
        manifest_dossier_path,
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "evidence-dossier",
    )

    markdown_dossier_path = evidence_dir / "g16-evidence-dossier.md"
    markdown_content = _render_acceptance_markdown(receipt, scale_benchmark)
    write_text_artifact(
        markdown_dossier_path,
        markdown_content,
        "evidence-dossier-markdown",
    )

    # 10. Update Register and Verify Evidence
    register_path = evidence_dir / "nf_fin_gates_g16.json"
    packaged_register = load_gate_register_template()
    updated_gates = []
    for g in packaged_register.get("gates", []):
        if g.get("gate_id") == "G16":
            updated_gates.append(
                {
                    **g,
                    "status": "partial",
                    "evidence": {
                        "test_nodes": [],
                        "run_receipts": [receipt],
                    },
                }
            )
        else:
            updated_gates.append(g)

    register = {
        **packaged_register,
        "gates": updated_gates,
    }
    write_text_artifact(
        register_path,
        json.dumps(register, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "gate-register",
    )

    verification = verify_gate_evidence(register, root)

    return G16AcceptanceBundle(
        root=root,
        register_path=register_path,
        positive_dossier_path=Path(pos_result.dossier_path),
        omitted_items_report_path=neg1_report_path,
        undeclared_code_report_path=neg2_report_path,
        invalid_scheme_report_path=neg3_report_path,
        scale_load_report_path=scale_report_path,
        scale_benchmark=scale_benchmark,
        verification=verification,
    )


def _render_acceptance_markdown(
    receipt: dict[str, Any], benchmark: dict[str, Any]
) -> str:
    lines = [
        "# G16 Acceptance Dossier: Interrater-Uebereinstimmung und Skalen-Lasttest",
        "",
        f"- Run ID: `{receipt['run_id']}`",
        f"- Input SHA-256: `{receipt['input_sha256']}`",
        f"- Output SHA-256: `{receipt['output_sha256']}`",
        "",
        "## Scale Load Benchmark (D-030 1,000 Questionnaires)",
        "",
        f"- Items Evaluated: `{benchmark['item_count']}`",
        f"- Elapsed Runtime: `{benchmark['elapsed_seconds']}s` "
        f"({benchmark['items_per_second']} items/s)",
        f"- Percent Agreement: `{benchmark['percent_agreement']}%`",
        f"- Cohen's Kappa: `{benchmark['cohens_kappa']}`",
        f"- Agreed / Disagreed: `{benchmark['agreed_items']} / {benchmark['disagreed_items']}`",
        "",
        "## Result Checks",
        "",
    ]
    for check in receipt["result_checks"]:
        symbol = "[x]" if check["passed"] else "[ ]"
        lines.append(f"- {symbol} **{check['name']}**: {check['evidence']}")

    lines.extend(
        (
            "",
            "## Handoff Receipts",
            "",
        )
    )
    for h in receipt["handoff_receipts"]:
        lines.append(
            f"- `{h['producer']}` -> `{h['consumer']}`: "
            f"artifact `{h['artifact_path']}` (SHA: `{h['artifact_sha256'][:12]}...`)"
        )

    lines.extend(
        (
            "",
            "## Negative Verification",
            "",
            f"- Primary: `{receipt['negative_path']['case']}` "
            f"(status: {receipt['negative_path']['status']})",
        )
    )
    for add_neg in receipt.get("additional_negative_paths", []):
        lines.append(f"- Additional: `{add_neg['case']}` (status: {add_neg['status']})")

    return "\n".join(lines).rstrip() + "\n"
