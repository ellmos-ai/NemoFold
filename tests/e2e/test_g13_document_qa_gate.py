"""Tests for Gate G13: Document QA and Publication Package (Ellmos UC 01, 39, 40)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.document_qa import (
    validate_document_qa,
)
from nemofold.job_io import parse_job_payload
from nemofold.voyage_runs import run_voyage


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


SAMPLE_WORKSHEET = (
    "# Autismus-Foerderblatt: Alltagsstrukturierung und Handlungssequenzen\n\n"
    "## Klient\n"
    "Klient: Max Mustermann · Alter: 11 Jahre · Modul: Autismus-Foerderung (UC 39)\n\n"
    "## Zielstellung\n"
    "Erstellung visueller Handlungssequenzen zur Foerderung der Selbststaendigkeit "
    "bei morgendlichen Alltagsablaeufen.\n\n"
    "## Uebung: Bildkarten-Reihenfolge ordnen\n"
    "1. Aufstehen und Wecker ausschalten\n"
    "2. Anziehen gemaess Kleiderkarten\n"
    "3. Fruehstueck und Zahnputz-Station\n\n"
    "## Reflexion und Verstaerkung\n"
    "Bei erfolgreicher Sequenzierung erhaelt das Kind einen Token fuer die Belohnungsbox.\n\n"
    "## Hinweispflicht\n"
    "Reine Foerder- und Beratungsmaterialien; keine heilkundliche Psychotherapie "
    "im Sinne des § 1 HeilprG.\n"
)


def test_validate_document_qa_positive(tmp_path: Path) -> None:
    doc_file = tmp_path / "foerderblatt.md"
    doc_file.write_text(SAMPLE_WORKSHEET, encoding="utf-8")
    actual_sha = _sha256(doc_file)

    result = validate_document_qa(
        SAMPLE_WORKSHEET,
        doc_file,
        expected_sha256=actual_sha,
        required_sections=("Klient", "Uebung", "Hinweispflicht"),
        disallow_unbound_fields=True,
        min_words=20,
        target_format="markdown",
    )

    assert result.passed is True
    assert result.document_sha256 == actual_sha
    assert result.detected_format == "markdown"
    assert len(result.errors) == 0
    assert len(result.unbound_fields) == 0
    assert len(result.checks) == 5
    assert all(c.passed for c in result.checks)


def test_validate_document_qa_detects_unbound_placeholders(tmp_path: Path) -> None:
    text_with_placeholders = (
        "# Beratungsblatt\n"
        "Klient: {{klient_name}} · Datum: [PLATZHALTER_DATUM]\n"
        "Ziel: <TODO: BESCHREIBUNG DER INTERVENTION>\n"
        "Uebung: Gedankenprotokoll fuehren gemaess Notiz.\n"
        "Hinweispflicht: Keine Heilbehandlung nach § 1 HeilprG.\n"
    )
    doc_file = tmp_path / "beratung.md"
    doc_file.write_text(text_with_placeholders, encoding="utf-8")

    result = validate_document_qa(
        text_with_placeholders,
        doc_file,
        disallow_unbound_fields=True,
    )

    assert result.passed is False
    assert len(result.unbound_fields) >= 3
    assert any("unbound_fields_in_document" in err for err in result.errors)


def test_validate_document_qa_detects_missing_required_sections(tmp_path: Path) -> None:
    text_incomplete = (
        "# Autismus-Foerderblatt\n"
        "Klient: Anna · Uebung: Bildkarten sortieren.\n"
    )
    doc_file = tmp_path / "incomplete.md"
    doc_file.write_text(text_incomplete, encoding="utf-8")

    result = validate_document_qa(
        text_incomplete,
        doc_file,
        required_sections=("Hinweispflicht", "Reflexion"),
    )

    assert result.passed is False
    assert any("document_incomplete:missing_required_sections" in err for err in result.errors)


def test_validate_document_qa_detects_hash_mismatch(tmp_path: Path) -> None:
    doc_file = tmp_path / "doc.md"
    doc_file.write_text(SAMPLE_WORKSHEET, encoding="utf-8")

    result = validate_document_qa(
        SAMPLE_WORKSHEET,
        doc_file,
        expected_sha256="0000000000000000000000000000000000000000000000000000000000000000",
    )

    assert result.passed is False
    assert any("source_document_hash_mismatch" in err for err in result.errors)


def test_execute_document_qa_positive_builds_publication_package(tmp_path: Path) -> None:
    doc_dir = tmp_path / "docs"
    doc_dir.mkdir(parents=True)
    doc_file = doc_dir / "arbeitsblatt.md"
    doc_file.write_text(SAMPLE_WORKSHEET, encoding="utf-8")
    actual_sha = _sha256(doc_file)

    out_dir = tmp_path / "out"
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "document_qa",
            "input_roots": [str(doc_dir)],
            "output_dir": str(out_dir),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "document_path": str(doc_file),
                "expected_sha256": actual_sha,
                "required_sections": ["Klient", "Uebung", "Hinweispflicht"],
                "package_title": "Autismus-Foerderblatt Publikationspaket",
            },
        },
        base_dir=tmp_path,
    )

    result = run_job(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="test_qa_01",
    )

    assert result.report.status is RunStatus.EXECUTED
    assert "publication_package_sealed" in result.report.actions

    qa_json = out_dir / "test_qa_01.document-qa.json"
    pkg_json = out_dir / "test_qa_01.publication-package.json"
    pkg_md = out_dir / "test_qa_01.publication-package.md"

    assert qa_json.is_file()
    assert pkg_json.is_file()
    assert pkg_md.is_file()

    payload = json.loads(pkg_json.read_text(encoding="utf-8"))
    assert payload["schema"] == "nemofold.publication-package.v1"
    assert payload["qa_passed"] is True
    assert payload["document_sha256"] == actual_sha
    assert payload["package_title"] == "Autismus-Foerderblatt Publikationspaket"
    assert payload["fallback_applied"] is True


def test_execute_document_qa_blocks_on_placeholders_and_emits_needs_input(
    tmp_path: Path,
) -> None:
    doc_dir = tmp_path / "docs"
    doc_dir.mkdir(parents=True)
    doc_file = doc_dir / "draft_with_placeholders.md"
    doc_file.write_text(
        "# Entwurf\n"
        "Klient: {{name}} · Intervention: [PLATZHALTER]\n"
        "Dosis: <TODO: DOSIS>\n",
        encoding="utf-8",
    )

    out_dir = tmp_path / "out"
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "document_qa",
            "input_roots": [str(doc_dir)],
            "output_dir": str(out_dir),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "document_path": str(doc_file),
            },
        },
        base_dir=tmp_path,
    )

    result = run_job(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="test_qa_blocked",
    )

    assert result.report.status is RunStatus.BLOCKED
    assert any("unbound_fields_in_document" in err for err in result.report.errors)
    needs_input = out_dir / "test_qa_blocked.needs-user-input.json"
    assert needs_input.is_file()
    needs_data = json.loads(needs_input.read_text(encoding="utf-8"))
    assert needs_data["schema"] == "nemofold.needs-user-input.v1"


def test_document_compose_blocks_when_report_forge_unavailable(tmp_path: Path) -> None:
    doc_dir = tmp_path / "docs"
    doc_dir.mkdir(parents=True)
    template = doc_dir / "template.docx"
    template.write_bytes(b"PK\x03\x04 not a real docx")

    out_dir = tmp_path / "out"
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "document_compose",
            "input_roots": [str(doc_dir)],
            "output_dir": str(out_dir),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {
                "template_path": str(template),
                "fields": {"title": "Test Title"},
            },
        },
        base_dir=tmp_path,
    )

    result = run_job(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path),)),
        run_id="test_compose_blocked",
    )

    assert result.report.status is RunStatus.BLOCKED
    assert "template_engine_unavailable" in result.report.errors
    blocked_json = out_dir / "test_compose_blocked.document-compose.json"
    assert blocked_json.is_file()
    data = json.loads(blocked_json.read_text(encoding="utf-8"))
    assert data["engine_available"] is False
    assert "report-forge" in data["boundary_note"]


def test_positive_voyage_knowledge_composer_document_qa_print_action(
    tmp_path: Path,
) -> None:
    # 1. Knowledge source fixtures (Ellmos UC 39 Autismus-Foerderung)
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir(parents=True)
    doc1 = kb_dir / "autismus_leitfaden.txt"
    doc1.write_text(
        "Foerderdokumentation Autismus-Spektrum\n"
        "Reizueberflutung: Hohe Laermempfindlichkeit bei wechselnden Geraeuschpegeln.\n"
        "Routinen: Feste Pausenzeiten um 12:00 Uhr und Vorankuendigung bei Raumwechseln.\n"
        "Kommunikation: Schriftliche Aufgabenstellung mit klaren Prioritaeten bevorzugt.\n"
        "Notfall-Anker: Zehn Minuten Rueckzug in den Ruheraum.\n",
        encoding="utf-8",
    )

    out1 = tmp_path / "step1_out"
    out2 = tmp_path / "step2_out"
    out3 = tmp_path / "step3_out"

    plan = {
        "voyage_id": "vy_g13_test_pos",
        "title": "G13 Positive 3-Step Voyage Test",
        "steps": [
            {
                "order": 1,
                "workflow": "knowledge_composer",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "knowledge_composer",
                    "input_roots": [str(kb_dir)],
                    "output_dir": str(out1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "profile": "autism_support",
                        "client_context": {
                            "client_name": "Max Mustermann",
                            "age": 11,
                            "module": "Autismus-Foerderung",
                        },
                        "title": "Autismus-Foerderblatt Alltagsstrukturierung",
                    },
                },
            },
            {
                "order": 2,
                "workflow": "document_qa",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_qa",
                    "input_roots": [str(out1)],
                    "output_dir": str(out2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "required_sections": ["Autismus", "Klientenkontext"],
                        "package_title": "Geprueftes Autismus-Foerderblatt Paket",
                    },
                },
            },
            {
                "order": 3,
                "workflow": "print_action",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "print_action",
                    "input_roots": [str(out2)],
                    "output_dir": str(out3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "source_id": "g13_test_pos_02.publication-package.md",
                    },
                },
            },
        ],
    }

    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    result = run_voyage(plan, config, run_id="g13_test_pos", base_dir=tmp_path)

    assert result.status == "executed"
    assert len(result.steps) == 3
    assert result.steps[0].status == "executed"
    assert result.steps[1].status == "executed"
    assert result.steps[2].status == "executed"

    # Step 2 artifacts
    pkg_json = out2 / "g13_test_pos_02.publication-package.json"
    assert pkg_json.is_file()
    pkg_data = json.loads(pkg_json.read_text(encoding="utf-8"))
    assert pkg_data["qa_passed"] is True

    # Step 3 artifacts
    print_instructions = out3 / "g13_test_pos_03.print-instructions.md"
    assert print_instructions.is_file()
