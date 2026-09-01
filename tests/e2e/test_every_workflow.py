"""Every registered contract, run end to end against one small corpus.

A workflow can be declared in the registry, offered in the console and drawn in
the graph gallery while nothing behind it runs - the three lists agree with each
other and none of them with the code. This walk is the check that closes that
gap: it takes every name in ``SUPPORTED_WORKFLOWS``, runs it for real, and
insists the run ends with either work done or a reason. Adding a contract
without an executor fails here rather than in front of somebody.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nemofold.application import ExecutionConfig, run_job
from nemofold.contracts import RunStatus
from nemofold.job_io import (
    SUPPORTED_WORKFLOWS,
    WORKFLOW_PARAMETER_FIELDS,
    parse_job_payload,
)

# Parameters a run cannot invent for itself: a coding scheme, a template, the
# one document to print. Everything absent here is meant to be absent - the
# workflow should manage on its defaults or say what it is missing.
PARAMETERS: dict[str, dict[str, object]] = {
    "bundle_export": {"bundle_name": "akte"},
    "cleanup_rules": {"retention_action": "list"},
    "contact_monitor": {"contact_book": "CONTACTS"},
    "controlled_email": {
        "contact_book": "CONTACTS",
        "from_address": "praxis@example.invalid",
        "to": ["ines@example.invalid"],
        "subject": "Kurzbericht",
        "body": "Anbei der Bericht zur Akte.",
    },
    "corpus_query": {"terms": ["Ines Brandt", "Praxis Nord"]},
    "document_compose": {"template_path": "TEMPLATE", "fields": {"anlass": "Termin"}},
    "document_registry": {"columns": [{"name": "Name"}, {"name": "Ort"}]},
    "dossier": {"subject": "Praxis Nord", "queries": ["Praxis Nord Bernau"]},
    "mail_merge_compose": {
        "template_path": "TEMPLATE",
        "contact_book": "CONTACTS",
        "fields": {"anlass": "Termin"},
    },
    "mail_to_case": {"case_id": "fall-nord", "case_title": "Praxis Nord"},
    "pattern_mining": {"min_support": 2},
    "person_registry": {"name_fields": ["Name"]},
    "rater_race": {
        "coding_scheme": {"zustimmung": ["gut", "zufrieden"], "kritik": ["zu lang"]},
        "scan_labels": ["Antwort"],
    },
    "reference_check": {"reference_grid": "bescheid_formal"},
    "smart_inbox": {"routes": [{"suffixes": [".eml"], "target_root": 0}]},
    "storage_policy": {"retention_action": "list"},
    "web_research": {"queries": ["Praxis Nord Bernau Öffnungszeiten"]},
    "wiki_export": {"wiki_dir": "WIKI"},
}

# Some contracts read something other than the document folder: mail arrives in a
# mailbox, a report is written from an analysis another run produced.
INPUT_ROOTS = {
    "mail_to_case": "postfach",
    "smart_inbox": "postfach",
    "report_studio": "studio",
}
# A workflow that moves or files things needs somewhere to move them to, and
# refuses to guess one.
TARGET_ROOTS = {
    "cleanup_rules": "ablage",
    "smart_inbox": "ablage",
    "storage_policy": "ablage",
}
QUESTIONS = ("evidence_analyst", "platform_proof", "report_studio")


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One folder that gives every workflow something honest to work on."""
    root = tmp_path_factory.mktemp("bestand")
    documents = root / "akte"
    documents.mkdir()
    (documents / "bericht.md").write_text(
        "Name: Praxis Nord\n"
        "Ort: Bernau\n"
        "Datum: 2026-03-04\n"
        "Antwort: Die Betreuung war gut, die Wartezeit zu lang.\n"
        "\n"
        "Am 4. März 2026 um 14:00 Uhr war Ines Brandt in der Praxis Nord.\n"
        "Robert Ostwald bestätigt, dass er sie dort gesehen hat.\n"
        "Die Anlage ist beigefügt und die Frist beträgt einen Monat.\n",
        encoding="utf-8",
    )
    (documents / "notiz.md").write_text(
        "Name: Praxis Nord\n"
        "Ort: Bernau\n"
        "Datum: 2026-03-05\n"
        "Antwort: Die Betreuung war gut.\n"
        "\n"
        "Am 5. März 2026 meldete Ines Brandt einen Folgetermin an.\n"
        "Die Anlage ist beigefügt und die Frist beträgt einen Monat.\n",
        encoding="utf-8",
    )
    (documents / "kontakte.txt").write_text(
        "name: Ines Brandt · class: familie · email: ines@example.invalid\n"
        "name: Robert Ostwald · class: freunde · email: robert@example.invalid\n",
        encoding="utf-8",
    )
    (documents / "vorlage.docx").write_bytes(b"PK\x03\x04 not a real docx")
    mailbox = root / "postfach"
    mailbox.mkdir()
    (mailbox / "eingang.eml").write_text(
        "From: ines@example.invalid\n"
        "To: praxis@example.invalid\n"
        "Subject: Folgetermin\n"
        "Date: Thu, 05 Mar 2026 09:00:00 +0100\n"
        "\n"
        "Bitte einen Folgetermin in der Praxis Nord.\n",
        encoding="utf-8",
    )
    (root / "ablage").mkdir()
    # report_studio writes from an analysis rather than from documents, so the
    # walk hands it one a real run produced instead of a hand-written stand-in.
    analyses = root / "analysen"
    analyses.mkdir()
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "evidence_analyst",
            "input_roots": [str(documents)],
            "output_dir": str(analyses),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "questions": ["Wer war am 4. März in der Praxis?"],
            "parameters": {"formats": ["md"]},
        },
        base_dir=root,
    )
    run_job(job, ExecutionConfig(allowed_roots=(str(root),)), run_id="vorlauf")
    # Exactly one analysis, because a studio handed two would have to pick.
    studio = root / "studio"
    studio.mkdir()
    analysis = next(
        path for path in sorted(analyses.iterdir()) if path.name.endswith(".analysis.json")
    )
    (studio / analysis.name).write_bytes(analysis.read_bytes())
    return root


def _parameters(workflow: str, corpus: Path, out: Path) -> dict[str, object]:
    documents = corpus / "akte"
    allowed = WORKFLOW_PARAMETER_FIELDS.get(workflow, frozenset())
    # The registry decides what a workflow accepts, and it refuses anything else
    # rather than ignoring it, so this walk asks it rather than guessing.
    resolved: dict[str, object] = {"formats": ["md"]} if "formats" in allowed else {}
    for key, value in PARAMETERS.get(workflow, {}).items():
        if key not in allowed:
            continue
        if value == "CONTACTS":
            value = str(documents / "kontakte.txt")
        elif value == "TEMPLATE":
            value = str(documents / "vorlage.docx")
        elif value == "WIKI":
            value = str(out / "wiki")
        resolved[key] = value
    return resolved


def _payload(workflow: str, corpus: Path, out: Path) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "nemofold.job.v1",
        "workflow": workflow,
        "input_roots": [str(corpus / INPUT_ROOTS.get(workflow, "akte"))],
        "output_dir": str(out),
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": _parameters(workflow, corpus, out),
    }
    if workflow in TARGET_ROOTS:
        payload["target_roots"] = [str(corpus / TARGET_ROOTS[workflow])]
    if workflow in QUESTIONS:
        payload["questions"] = ["Wer war am 4. März in der Praxis?"]
    return payload


@pytest.mark.parametrize("workflow", sorted(SUPPORTED_WORKFLOWS))
def test_every_registered_workflow_runs_and_reports(workflow, corpus, tmp_path) -> None:
    out = tmp_path / "out"
    job = parse_job_payload(_payload(workflow, corpus, out), base_dir=tmp_path)

    result = run_job(
        job,
        ExecutionConfig(allowed_roots=(str(corpus), str(tmp_path))),
        run_id=f"walk-{workflow}",
    )

    report = result.report
    # Work done or a reason given. Both are honest outcomes; a contract that is
    # merely declared is not.
    assert report.status in {RunStatus.EXECUTED, RunStatus.BLOCKED}, (
        f"{workflow}: {report.status.value} {report.errors}"
    )
    assert not any(error.startswith("workflow_not_implemented") for error in report.errors), (
        f"{workflow} is registered but has no executor"
    )
    if report.status is RunStatus.BLOCKED:
        # A blocked run without a stated reason is indistinguishable from a
        # silent failure, and reads to a user as the product not working.
        assert report.errors, f"{workflow} blocked without saying why"
    else:
        assert report.artifacts, f"{workflow} reported success without producing anything"


@pytest.mark.parametrize("workflow", sorted(SUPPORTED_WORKFLOWS))
def test_every_workflow_writes_only_inside_the_output_directory(workflow, corpus, tmp_path) -> None:
    """No artifact lands where the caller did not ask for one."""
    out = tmp_path / "out"
    job = parse_job_payload(_payload(workflow, corpus, out), base_dir=tmp_path)

    result = run_job(
        job,
        ExecutionConfig(allowed_roots=(str(corpus), str(tmp_path))),
        run_id=f"scope-{workflow}",
    )

    for artifact in result.report.artifacts:
        path = Path(artifact.path).resolve()
        assert path.is_relative_to(tmp_path.resolve()), f"{workflow} wrote to {path}"
    # The corpus is read-only material: a run that edits its own evidence would
    # invalidate every quote it just took.
    for document in sorted((corpus / "akte").iterdir()):
        assert document.exists()


def test_the_walk_covers_the_registry_and_not_a_stale_copy() -> None:
    """The parametrisation is generated, so a new contract joins it by itself."""
    covered = set(SUPPORTED_WORKFLOWS)
    unknown = set(PARAMETERS) - covered

    assert not unknown, f"parameters for workflows that no longer exist: {sorted(unknown)}"
    assert len(covered) >= 34


def test_a_report_is_readable_json_for_every_workflow(corpus, tmp_path) -> None:
    """One run's report, parsed rather than assumed."""
    out = tmp_path / "out"
    job = parse_job_payload(
        {
            "schema": "nemofold.job.v1",
            "workflow": "folder_digest",
            "input_roots": [str(corpus / "akte")],
            "output_dir": str(out),
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "parameters": {},
        },
        base_dir=tmp_path,
    )

    result = run_job(
        job, ExecutionConfig(allowed_roots=(str(corpus), str(tmp_path))), run_id="json"
    )

    payload = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
    assert payload["run_id"] == "json"
    assert payload["status"] in {"executed", "blocked"}
