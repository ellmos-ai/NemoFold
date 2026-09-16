"""End-to-end tests for Gate G09: Grounded Document Generation from Knowledge (UC 1, 39, 40)."""

from __future__ import annotations

import json
from pathlib import Path

from nemofold.application import ExecutionConfig
from nemofold.knowledge_composer import (
    COUNSELING_DISCLAIMER_NOTICE,
    SOURCE_GROUNDING_NOTICE,
    parse_autism_knowledge_from_texts,
    parse_counseling_knowledge_from_texts,
    parse_cv_stations_from_texts,
    render_ascii_cv,
    render_worksheet_markdown,
)
from nemofold.voyage_runs import run_voyage


def _create_sample_cv_sources(path: Path) -> list[Path]:
    f1 = path / "zeugnis_techcorp.txt"
    f1.write_text(
        "Arbeitszeugnis\n"
        "Arbeitgeber: TechCorp GmbH\n"
        "Position: Senior Python Developer\n"
        "Zeitraum: 2021 - 2024\n"
        "Aufgaben: Entwicklung verteilter Microservices und Mentoring von Juniorentwicklern.\n",
        encoding="utf-8",
    )
    f2 = path / "zeugnis_dataflow.txt"
    f2.write_text(
        "Referenzschreiben\n"
        "Unternehmen: DataFlow Systems\n"
        "Position: Software Architect\n"
        "Zeitraum: 2024 - heute\n"
        "Aufgaben: Design modularer Datenpipelines und Einhaltung von Sicherheitsarchitekturen.\n",
        encoding="utf-8",
    )
    return [f1, f2]


def _create_sample_autism_sources(path: Path) -> Path:
    f = path / "autismus_foerderbericht.txt"
    f.write_text(
        "Förderdokumentation Autismus-Spektrum\n"
        "Reizüberflutung: Hohe Lärmempfindlichkeit im Büro bei "
        "wechselnden Geräuschpegeln.\n"
        "Routinen: Feste Pausenzeiten um 12:00 Uhr und Vorankündigung bei Raumwechseln.\n"
        "Kommunikation: Schriftliche Aufgabenstellung mit klaren Prioritäten bevorzugt.\n"
        "Notfall-Anker: Zehn Minuten Rückzug in den Ruheraum mit "
        "Noise-Cancelling-Kopfhörern.\n",
        encoding="utf-8",
    )
    return f


def _create_sample_counseling_sources(path: Path) -> Path:
    f = path / "beratungsnotizen.txt"
    f.write_text(
        "Protokoll Psychologische Beratung\n"
        "Zieldefinition: Bessere Abgrenzung gegen Überstunden und feste Feierabendzeiten.\n"
        "Ressourcen: Starkes privates Unterstützungsnetzwerk und fundierte Fachkompetenz.\n"
        "Glaubenssätze: 'Ich darf Kollegen niemals mit Arbeit allein lassen.'\n"
        "Transferaufgabe: Zweimal pro Woche pünktlich um 17:00 Uhr das Büro verlassen.\n",
        encoding="utf-8",
    )
    return f


# --------------------------------------------------------------------------- #
# Unit Tests
# --------------------------------------------------------------------------- #


def test_parse_cv_stations_from_texts(tmp_path: Path) -> None:
    sources = _create_sample_cv_sources(tmp_path)
    texts = {p.stem: p.read_text(encoding="utf-8") for p in sources}
    stations = parse_cv_stations_from_texts(texts)

    assert len(stations) == 2
    employers = {s.employer for s in stations}
    assert "TechCorp GmbH" in employers
    assert "DataFlow Systems" in employers

    ascii_cv = render_ascii_cv(stations, {"name": "Lukas G.", "contact": "lukas@example.org"})
    assert "CURRICULUM VITAE" in ascii_cv
    assert "Lukas G." in ascii_cv
    assert "TechCorp GmbH" in ascii_cv
    assert "DataFlow Systems" in ascii_cv
    assert SOURCE_GROUNDING_NOTICE in ascii_cv


def test_parse_autism_knowledge_from_texts(tmp_path: Path) -> None:
    source = _create_sample_autism_sources(tmp_path)
    texts = {source.stem: source.read_text(encoding="utf-8")}
    tasks = parse_autism_knowledge_from_texts(texts)

    assert len(tasks) >= 4
    categories = {t.category for t in tasks}
    assert "Reizüberflutung" in categories
    assert "Routinen" in categories
    assert "Notfall-Anker" in categories

    md = render_worksheet_markdown(
        "autism_support",
        "Autismus-Förderblatt",
        tasks,
        {"client_name": "Alex", "mentor": "Dr. Weber"},
    )
    assert "Autismus-Förderblatt" in md
    assert "Alex" in md
    assert SOURCE_GROUNDING_NOTICE in md


def test_parse_counseling_knowledge_from_texts(tmp_path: Path) -> None:
    source = _create_sample_counseling_sources(tmp_path)
    texts = {source.stem: source.read_text(encoding="utf-8")}
    tasks = parse_counseling_knowledge_from_texts(texts)

    assert len(tasks) >= 4
    categories = {t.category for t in tasks}
    assert "Zieldefinition" in categories
    assert "Ressourcen" in categories
    assert "Glaubenssätze" in categories

    md = render_worksheet_markdown(
        "counseling_worksheet",
        "Beratungs-Arbeitsblatt",
        tasks,
        {"client_name": "Maria", "counselor": "Coach Sarah"},
    )
    assert "Beratungs-Arbeitsblatt" in md
    assert "Maria" in md
    assert COUNSELING_DISCLAIMER_NOTICE in md
    assert SOURCE_GROUNDING_NOTICE in md


# --------------------------------------------------------------------------- #
# E2E Voyage Tests
# --------------------------------------------------------------------------- #


def test_g09_positive_cv_voyage(tmp_path: Path) -> None:
    input_dir = tmp_path / "cv_sources"
    input_dir.mkdir(parents=True)
    _create_sample_cv_sources(input_dir)

    out_step1 = tmp_path / "out_reg"
    out_step2 = tmp_path / "out_cv"
    out_step3 = tmp_path / "out_digest"

    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g09_positive_cv",
        "title": "G09 Positive CV Generation Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "document_registry",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "document_registry",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "column_template": "inventory",
                        "formats": ["json"],
                    },
                },
            },
            {
                "order": 2,
                "workflow": "knowledge_composer",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "knowledge_composer",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step2),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "profile": "cv_ascii",
                        "title": "Curriculum Vitae - Lukas G.",
                        "client_context": {
                            "name": "Lukas G.",
                            "contact": "lukas@example.org",
                        },
                        "min_knowledge_items": 2,
                        "formats": ["md", "json", "txt"],
                    },
                },
            },
            {
                "order": 3,
                "workflow": "folder_digest",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "folder_digest",
                    "input_roots": [str(out_step2)],
                    "output_dir": str(out_step3),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {"summary_length": 3},
                },
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g09_pos_cv")
    assert result.status == "executed"
    assert len(result.steps) == 3

    step2_json = out_step2 / "g09_pos_cv_02.knowledge-composer.json"
    step2_md = out_step2 / "g09_pos_cv_02.knowledge-composer.md"
    step2_txt = out_step2 / "g09_pos_cv_02.cv.txt"

    assert step2_json.is_file()
    assert step2_md.is_file()
    assert step2_txt.is_file()

    payload = json.loads(step2_json.read_text(encoding="utf-8"))
    assert payload["profile"] == "cv_ascii"
    assert payload["total_stations"] == 2
    assert "TechCorp GmbH" in str(payload["stations"])
    assert "DataFlow Systems" in str(payload["stations"])


def test_g09_positive_autism_voyage(tmp_path: Path) -> None:
    input_dir = tmp_path / "autism_sources"
    input_dir.mkdir(parents=True)
    _create_sample_autism_sources(input_dir)

    out_step1 = tmp_path / "out_autism"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g09_positive_autism",
        "title": "G09 Positive Autism Worksheet Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "knowledge_composer",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "knowledge_composer",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "profile": "autism_support",
                        "title": "Förderarbeitsblatt Autismus",
                        "client_context": {"client_name": "Alex"},
                        "min_knowledge_items": 3,
                        "formats": ["md", "json"],
                    },
                },
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g09_pos_aut")
    assert result.status == "executed"
    out_json = out_step1 / "g09_pos_aut_01.knowledge-composer.json"
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["profile"] == "autism_support"
    assert payload["total_tasks"] >= 4


def test_g09_positive_counseling_voyage(tmp_path: Path) -> None:
    input_dir = tmp_path / "counseling_sources"
    input_dir.mkdir(parents=True)
    _create_sample_counseling_sources(input_dir)

    out_step1 = tmp_path / "out_counseling"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g09_positive_counseling",
        "title": "G09 Positive Counseling Worksheet Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "knowledge_composer",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "knowledge_composer",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step1),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "profile": "counseling_worksheet",
                        "title": "Beratungsblatt Stressreduktion",
                        "client_context": {"client_name": "Maria"},
                        "min_knowledge_items": 3,
                        "formats": ["md", "json"],
                    },
                },
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g09_pos_counsel")
    assert result.status == "executed"
    out_json = out_step1 / "g09_pos_counsel_01.knowledge-composer.json"
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["profile"] == "counseling_worksheet"
    assert "HeilprG" in payload["audit_notice"]


# --------------------------------------------------------------------------- #
# Negative Voyage Tests (Blocking Gates)
# --------------------------------------------------------------------------- #


def test_g09_insufficient_knowledge_blocks_voyage(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty_sources"
    empty_dir.mkdir(parents=True)
    empty_file = empty_dir / "leer.txt"
    empty_file.write_text("Hier steht nichts Relevantes drin.", encoding="utf-8")

    out_step = tmp_path / "out_insufficient"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g09_neg_insufficient",
        "title": "G09 Negative Insufficient Knowledge Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "knowledge_composer",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "knowledge_composer",
                    "input_roots": [str(empty_dir)],
                    "output_dir": str(out_step),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "profile": "cv_ascii",
                        "min_knowledge_items": 1,
                    },
                },
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g09_neg_insuf")
    assert result.status == "stopped"
    assert result.steps[-1].status == "blocked"
    needs_input = out_step / "g09_neg_insuf_01.needs-user-input.json"
    assert needs_input.is_file()
    payload = json.loads(needs_input.read_text(encoding="utf-8"))
    assert "Es konnten keine ausreichenden belegten Wissenseinheiten" in (
        payload["questions"][0]["prompt"]
    )


def test_g09_unanchored_claim_blocks_voyage(tmp_path: Path) -> None:
    input_dir = tmp_path / "cv_sources_unanchored"
    input_dir.mkdir(parents=True)
    _create_sample_cv_sources(input_dir)

    out_step = tmp_path / "out_unanchored"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g09_neg_unanchored",
        "title": "G09 Negative Unanchored Claim Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "knowledge_composer",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "knowledge_composer",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "profile": "cv_ascii",
                        "forbidden_unanchored_claim": "Quantencomputing-Nobelpreisträger",
                    },
                },
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g09_neg_unanchored")
    assert result.status == "stopped"
    assert result.steps[-1].status == "blocked"
    assert result.steps[-1].ledger_path is not None
    report = json.loads(Path(result.steps[-1].ledger_path).read_text(encoding="utf-8"))
    assert any("unanchored_claim_blocked" in f for f in report["errors"])


def test_g09_missing_client_context_blocks_voyage(tmp_path: Path) -> None:
    input_dir = tmp_path / "autism_sources_missing_ctx"
    input_dir.mkdir(parents=True)
    _create_sample_autism_sources(input_dir)

    out_step = tmp_path / "out_missing_ctx"
    config = ExecutionConfig(allowed_roots=(str(tmp_path),))
    plan = {
        "voyage_id": "vy_g09_neg_missing_ctx",
        "title": "G09 Negative Missing Context Voyage",
        "steps": [
            {
                "order": 1,
                "workflow": "knowledge_composer",
                "job": {
                    "schema": "nemofold.job.v1",
                    "workflow": "knowledge_composer",
                    "input_roots": [str(input_dir)],
                    "output_dir": str(out_step),
                    "privacy_mode": "local_only",
                    "action_mode": "dry_run",
                    "parameters": {
                        "profile": "autism_support",
                        # Missing client_context on purpose
                    },
                },
            },
        ],
    }

    result = run_voyage(plan, config, run_id="g09_neg_missing_ctx")
    assert result.status == "stopped"
    assert result.steps[-1].status == "blocked"
    assert result.steps[-1].ledger_path is not None
    report = json.loads(Path(result.steps[-1].ledger_path).read_text(encoding="utf-8"))
    assert any("missing_target_context" in f for f in report["errors"])
