from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.job_io import parse_job_payload
from nemofold.policies import PolicyStore, resolve_refs


def _job(tmp_path: Path, workflow: str, documents: Path, **parameters):
    return parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": workflow,
            "input_roots": [str(documents)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": parameters.pop("action_mode", "dry_run"),
            "parameters": parameters,
        },
        base_dir=tmp_path,
    )


@pytest.fixture
def registry_corpus(tmp_path: Path) -> Path:
    documents = tmp_path / "akte"
    documents.mkdir()
    (documents / "bericht.md").write_text(
        "Name: Praxis Nord\nFachrichtung: Orthopädie\n", encoding="utf-8"
    )
    return documents


# --------------------------------------------------------------------------- #
# The run asks back rather than shipping a hole
# --------------------------------------------------------------------------- #


def test_a_required_column_the_sources_do_not_answer_stops_the_run(
    tmp_path, registry_corpus
) -> None:
    job = _job(
        tmp_path,
        "document_registry",
        registry_corpus,
        columns=[{"name": "Name"}, {"name": "Fachrichtung"}, {"name": "Kontakt"}],
        required_columns=["Kontakt"],
        formats=["md"],
    )

    result = run_job(job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="asked")

    assert result.report.status is RunStatus.BLOCKED
    assert result.report.metadata["needs_user_input"] is True
    payload = json.loads(
        (tmp_path / "out" / "asked.needs-user-input.json").read_text(encoding="utf-8")
    )
    question = payload["questions"][0]
    # The question names the field, the document and the reason, which is what
    # makes it answerable rather than merely a complaint.
    assert question["field"] == "columns.Kontakt"
    assert "Praxis Nord" in question["prompt"] or "bericht" in question["prompt"]
    assert "Pflichtspalte" in question["why"]
    assert "would otherwise have guessed" in payload["outcome_note"]


def test_a_column_nobody_required_leaves_the_cell_empty_without_asking(
    tmp_path, registry_corpus
) -> None:
    job = _job(
        tmp_path,
        "document_registry",
        registry_corpus,
        columns=[{"name": "Name"}, {"name": "Kontakt"}],
        formats=["md"],
    )

    result = run_job(job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="quiet")

    # Empty stays honestly empty. Asking about every gap would be its own kind
    # of noise, so only a declared requirement produces a question.
    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata.get("needs_user_input") is None


# --------------------------------------------------------------------------- #
# A finished run files what it produced
# --------------------------------------------------------------------------- #


def test_fact_distill_files_its_output_where_the_rule_says(tmp_path) -> None:
    documents = tmp_path / "akte"
    documents.mkdir()
    (documents / "notiz.md").write_text(
        "Die Deckung beginnt am 1. April 2026.\nDer Beitrag betraegt 148 Euro pro Jahr.\n",
        encoding="utf-8",
    )
    ablage = tmp_path / "ablage"

    job = _job(
        tmp_path,
        "fact_distill",
        documents,
        formats=["md"],
        action_mode="apply",
        delivery_policy={
            "routes": [{"artifact_kind": "markdown", "target_root": str(ablage)}]
        },
    )
    result = run_job(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path),), apply_actions_allowed=True),
        run_id="filed",
    )

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["delivery_applied"] is True
    receipt = json.loads((tmp_path / "out" / "filed.delivery.json").read_text("utf-8"))
    assert receipt["delivered_count"] >= 1
    assert list(ablage.glob("*.md"))


def test_a_delivery_target_outside_the_roots_does_not_stop_the_findings(tmp_path) -> None:
    documents = tmp_path / "akte"
    documents.mkdir()
    (documents / "notiz.md").write_text("Der Beitrag betraegt 148 Euro.\n", encoding="utf-8")
    outside = tmp_path.parent / "fremd"

    job = _job(
        tmp_path,
        "fact_distill",
        documents,
        formats=["md"],
        action_mode="apply",
        delivery_policy={
            "routes": [{"artifact_kind": "markdown", "target_root": str(outside)}]
        },
    )
    result = run_job(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path),), apply_actions_allowed=True),
        run_id="refused",
    )

    # The findings are still produced; only the filing is refused, and the
    # receipt says why rather than the run failing over a convenience.
    assert result.report.status is RunStatus.EXECUTED
    receipt = json.loads((tmp_path / "out" / "refused.delivery.json").read_text("utf-8"))
    assert receipt["delivered_count"] == 0
    refused_entry = next(
        item for item in receipt["receipts"] if item["artifact_kind"] == "markdown"
    )
    assert "outside the approved roots" in refused_entry["reason"]
    assert "approve that root first" in receipt["notes"][0]
    assert not outside.exists()


# --------------------------------------------------------------------------- #
# xlsx and print through the contract
# --------------------------------------------------------------------------- #


def test_a_report_can_be_rendered_as_a_workbook(tmp_path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    documents = tmp_path / "akte"
    documents.mkdir()
    (documents / "notiz.md").write_text(
        "Die Deckung beginnt am 1. April 2026.\n", encoding="utf-8"
    )

    job = _job(tmp_path, "fact_distill", documents, formats=["md", "xlsx"])
    result = run_job(job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="book")

    assert result.report.status is RunStatus.EXECUTED
    book = next(
        Path(item.path) for item in result.report.artifacts if item.format == "xlsx"
    )
    sheet = openpyxl.load_workbook(io.BytesIO(book.read_bytes())).active
    header = [cell for cell in next(sheet.iter_rows(values_only=True))]
    assert header == ["Aussage", "Quelle", "Fundstelle", "Zitat"]
    # The workbook is a different reading of the same findings, and stays
    # byte-stable so its ledger hash means something.
    again = book.read_bytes()
    assert hashlib.sha256(again).hexdigest() == next(
        item.sha256 for item in result.report.artifacts if item.format == "xlsx"
    )


def test_print_action_prepares_a_file_and_says_it_did_not_print(tmp_path) -> None:
    documents = tmp_path / "akte"
    documents.mkdir()
    (documents / "bericht.md").write_text("# Bericht", encoding="utf-8")

    job = _job(tmp_path, "print_action", documents, formats=["md"])
    result = run_job(job, ExecutionConfig(allowed_roots=(str(tmp_path),)), run_id="printed")

    assert result.report.status is RunStatus.EXECUTED
    assert result.report.metadata["printed"] is False
    note = next(Path(item.path) for item in result.report.artifacts
                if item.format == "print-instructions")
    assert "Start-Process" in note.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# One answer, whichever way a policy was attached
# --------------------------------------------------------------------------- #


def test_a_binding_and_a_named_reference_fold_into_one_answer(tmp_path) -> None:
    store = PolicyStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))
    bound = store.save(
        {"name": "Gebunden", "form": "rule", "statements": ["Gilt über die Bindung."]}
    )
    store.bind(bound["policy_id"], target="voyage", voyage_id="voyage_a")
    named = store.save(
        {"name": "Benannt", "form": "rule", "statements": ["Gilt über den Namen."]}
    )

    found, unresolved = resolve_refs(
        store.list(),
        voyage_id="voyage_a",
        policy_refs=(named["policy_id"], "Benannt", "gibt es nicht"),
    )

    # Both mechanisms answer the same question, and the same policy named twice
    # is still one policy.
    assert sorted(item["name"] for item in found) == ["Benannt", "Gebunden"]
    # A reference to something deleted is a finding, not a blank.
    assert unresolved == ("gibt es nicht",)


def test_recipient_classes_live_in_the_register(tmp_path) -> None:
    store = PolicyStore(base_dir=tmp_path, allowed_roots=(str(tmp_path),))

    saved = store.save(
        {
            "name": "Empfängerklassen",
            "form": "policy",
            "kind": "recipient_classes",
            "statements": ["Familie darf auf Anweisung, öffentlich nie."],
            "body": {
                "contact_book": "kontakte.txt",
                "class_rights": {"familie": "send_when_ordered", "oeffentlich": "draft_only"},
            },
        }
    )

    assert saved["body"]["class_rights"]["familie"] == "send_when_ordered"
    assert saved["body"]["contact_book"] == "kontakte.txt"
    with pytest.raises(ValueError, match="must map to draft_only"):
        store.save(
            {
                "name": "Kaputt",
                "form": "policy",
                "kind": "recipient_classes",
                "statements": ["x"],
                "body": {"class_rights": {"familie": "send_anything"}},
            }
        )
