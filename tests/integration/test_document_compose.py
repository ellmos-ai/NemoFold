from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.document_compose import (
    EXTRA_NAME,
    INSTALL_HINT,
    ComposeRequest,
    TemplateEngineUnavailable,
    compose_documents,
    compose_payload,
    engine_status,
    payload_for,
    plan_merge,
)
from nemofold.job_io import parse_job_payload
from nemofold.structured_sources import Contact


def _contact(name: str, klass: str = "familie") -> Contact:
    return Contact(
        name=name,
        contact_class=klass,
        email=f"{name.split()[0].casefold()}@example.invalid",
        phone="",
        note="",
        line=1,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    documents = tmp_path / "vorlagen"
    documents.mkdir()
    (documents / "einladung.docx").write_bytes(b"PK\x03\x04 not a real docx")
    (documents / "gaeste.txt").write_text(
        "name: Ines Brandt · class: familie · email: ines@example.invalid\n"
        "name: Robert Ostwald · class: freunde · email: robert@example.invalid\n",
        encoding="utf-8",
    )
    return documents


def _job(tmp_path: Path, documents: Path, workflow: str, run_id: str, **parameters):
    payload = {"template_path": str(documents / "einladung.docx")}
    payload.update(parameters)
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": workflow,
            "input_roots": [str(documents)],
            "output_dir": str(tmp_path / "out"),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": payload,
        },
        base_dir=tmp_path,
    )
    return run_job(
        job,
        ExecutionConfig(allowed_roots=(str(tmp_path), str(documents))),
        run_id=run_id,
    )


# --------------------------------------------------------------------------- #
# The merge plan is ours; the filling is not
# --------------------------------------------------------------------------- #


def test_a_contact_value_wins_over_a_shared_field() -> None:
    merged = payload_for({"name": "Platzhalter", "anlass": "Hochzeit"}, _contact("Ines Brandt"))

    # A shared field overriding the recipient would produce five hundred letters
    # to the same person.
    assert merged["name"] == "Ines Brandt"
    assert merged["anlass"] == "Hochzeit"


def test_without_a_contact_book_exactly_one_document_is_planned(tmp_path) -> None:
    requests, notes = plan_merge({"anlass": "Hochzeit"}, "vorlage.docx", str(tmp_path))

    assert len(requests) == 1
    assert requests[0].recipient == ""
    assert notes == ()


def test_every_recipient_gets_a_document_named_after_them(workspace, tmp_path) -> None:
    requests, notes = plan_merge(
        {"anlass": "Hochzeit"},
        str(workspace / "einladung.docx"),
        str(tmp_path),
        contact_book=str(workspace / "gaeste.txt"),
        basename="einladung",
    )

    assert [item.recipient for item in requests] == ["Ines Brandt", "Robert Ostwald"]
    # A folder of near-identical documents nobody can tell apart is its own
    # kind of failure.
    assert [item.basename for item in requests] == [
        "einladung-ines-brandt",
        "einladung-robert-ostwald",
    ]
    assert notes == ()


def test_a_merge_beyond_its_ceiling_is_refused(tmp_path) -> None:
    book = tmp_path / "viele.txt"
    book.write_text(
        "".join(
            f"name: Gast {index} · class: freunde · email: g{index}@example.invalid\n"
            for index in range(501)
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="may not exceed 500 recipients"):
        plan_merge({}, "vorlage.docx", str(tmp_path), contact_book=str(book))


# --------------------------------------------------------------------------- #
# The optional engine is absent honestly
# --------------------------------------------------------------------------- #


def test_the_status_names_the_extra_and_the_install_command() -> None:
    status = engine_status()

    if status.available:
        pytest.skip("the templates extra is installed in this environment")
    assert EXTRA_NAME in status.reason
    assert INSTALL_HINT in status.reason


def test_composing_without_the_engine_refuses_rather_than_importing() -> None:
    if engine_status().available:
        pytest.skip("the templates extra is installed in this environment")

    with pytest.raises(TemplateEngineUnavailable, match=EXTRA_NAME):
        compose_documents(
            (ComposeRequest("vorlage.docx", {}, ".", "x"),),
        )


def test_a_run_without_the_engine_blocks_with_the_install_command(workspace, tmp_path):
    if engine_status().available:
        pytest.skip("the templates extra is installed in this environment")

    result = _job(
        tmp_path, workspace, "document_compose", "compose", fields={"anlass": "Hochzeit"}
    )

    # A workspace that renders evidence should not fail to start because a
    # template engine is missing, so this is a blocked outcome and not a crash.
    assert result.report.status is RunStatus.BLOCKED
    assert "template_engine_unavailable" in result.report.errors
    assert result.report.metadata["template_engine_available"] is False
    payload = json.loads(
        (tmp_path / "out" / "compose.document-compose.json").read_text(encoding="utf-8")
    )
    assert payload["written"] == 0
    assert INSTALL_HINT in payload["engine_note"]
    assert "does not fill templates itself" in payload["boundary_note"]


def test_a_mail_merge_plans_every_recipient_even_without_the_engine(workspace, tmp_path):
    if engine_status().available:
        pytest.skip("the templates extra is installed in this environment")

    result = _job(
        tmp_path,
        workspace,
        "mail_merge_compose",
        "merge",
        contact_book=str(workspace / "gaeste.txt"),
        fields={"anlass": "Hochzeit"},
        basename="einladung",
    )

    assert result.report.status is RunStatus.BLOCKED
    assert result.report.metadata["planned_documents"] == 2
    payload = json.loads(
        (tmp_path / "out" / "merge.document-compose.json").read_text(encoding="utf-8")
    )
    assert payload["recipients"] == ["Ines Brandt", "Robert Ostwald"]


# --------------------------------------------------------------------------- #
# Templates obey the same boundary as everything else
# --------------------------------------------------------------------------- #


def test_a_template_outside_the_approved_roots_is_refused(workspace, tmp_path) -> None:
    outside = tmp_path.parent / "fremd.docx"
    outside.write_bytes(b"PK\x03\x04")

    result = _job(
        tmp_path, workspace, "document_compose", "outside", template_path=str(outside)
    )

    assert result.report.status is RunStatus.FAILED


def test_a_template_that_does_not_exist_is_refused(workspace, tmp_path) -> None:
    result = _job(
        tmp_path,
        workspace,
        "document_compose",
        "missing",
        template_path=str(workspace / "gibtesnicht.docx"),
    )

    assert result.report.status is RunStatus.FAILED


def test_the_payload_never_claims_an_unconfirmed_document() -> None:
    status = engine_status()
    payload = compose_payload(
        (ComposeRequest("v.docx", {}, ".", "x"),), (), ("engine refused",), status
    )

    assert payload["written"] == 0
    assert payload["documents"] == []
    assert "not confirmed" in payload["boundary_note"] or "did not confirm" in (
        payload["boundary_note"]
    )
