from __future__ import annotations

import pytest

from nemofold.job_io import SUPPORTED_WORKFLOWS, parse_job_payload, validate_workflow_parameters
from nemofold.wizard import VOYAGE_SCHEMA, plan_to_primitive, plan_voyage

# The two requests the user wrote himself, kept verbatim.
ACCIDENT_REQUEST = (
    "Unfall mit Hyundai und schreib mir eine mail an zuständigen versicherungsberater "
    "füge bild ein als entwurf"
)
BILINGUAL_REQUEST = (
    "dokument das bilingual vorliegt regelmäßig abgleichen und auf den neuesten stand bringen"
)


def test_accident_request_prepares_a_controlled_email_draft(tmp_path) -> None:
    plan = plan_voyage(ACCIDENT_REQUEST, input_roots=(str(tmp_path),))

    workflows = [step.workflow for step in plan.steps]
    assert "controlled_email" in workflows
    # The mail is the goal, so it comes last in the chain.
    assert workflows[-1] == "controlled_email"
    # Any preceding step must be one the keyword table can justify.
    assert set(workflows[:-1]) <= {"contact_monitor", "mail_to_case", "evidence_analyst"}

    email = next(step for step in plan.steps if step.workflow == "controlled_email")
    questions = " ".join(email.questions_to_user)
    assert "Which address should receive the draft?" in email.questions_to_user
    assert "attached" in questions  # the image is asked for as an attachment
    assert "not read as evidence" in questions
    assert email.job["parameters"]["send_requested"] is False
    assert email.job["parameters"]["to"] == []
    assert email.job["action_mode"] == "dry_run"
    assert email.job["privacy_mode"] == "local_only"
    # The request text seeds the subject so the draft is recognisable.
    assert "Hyundai" in email.job["parameters"]["subject"]


def test_accident_request_names_sending_as_unavailable_only_when_asked() -> None:
    asked_to_send = plan_voyage(ACCIDENT_REQUEST + " und versende sie direkt")
    keys = {item.key for item in asked_to_send.unavailable}
    assert "mail_delivery" in keys
    delivery = next(item for item in asked_to_send.unavailable if item.key == "mail_delivery")
    assert "server-side mail adapter" in delivery.reason

    # Without a send verb the plan does not invent a refusal.
    assert "mail_delivery" not in {item.key for item in plan_voyage(ACCIDENT_REQUEST).unavailable}


def test_bilingual_request_is_answered_honestly_with_an_approximation() -> None:
    plan = plan_voyage(BILINGUAL_REQUEST, input_roots=("examples/synthetic-home",))

    bilingual = next(item for item in plan.unavailable if item.key == "bilingual_sync")
    assert "planned Document Service" in bilingual.reason
    assert "cannot align two language versions" in bilingual.reason
    assert bilingual.alternative_workflows == ("folder_digest", "version_resolver")
    assert "Version Resolver" in bilingual.approximation

    # The alternatives are not just named, they are prepared.
    workflows = [step.workflow for step in plan.steps]
    assert workflows == ["folder_digest", "version_resolver"]


def test_bilingual_request_answers_repetition_without_claiming_a_scheduler() -> None:
    plan = plan_voyage(BILINGUAL_REQUEST)

    assert plan.recurring is not None
    assert plan.recurring.requested is True
    assert "no scheduler of its own" in plan.recurring.message
    assert len(plan.recurring.options) == 2
    joined = " ".join(plan.recurring.options)
    assert "Run the prepared drafts again" in joined
    assert "your own operating system" in joined
    assert "cron" not in joined.casefold()


def test_requests_without_repetition_carry_no_recurring_block() -> None:
    assert plan_voyage("bündel die unterlagen").recurring is None


def test_every_planned_step_is_a_valid_job_for_an_active_workflow(tmp_path) -> None:
    requests = (
        ACCIDENT_REQUEST,
        BILINGUAL_REQUEST,
        "sortiere den posteingang und erstelle danach einen bericht",
        "analysiere die verträge auf widersprüche und bündle die belege",
        "räum den ordner auf und lege eine namenskonvention fest",
    )
    for request in requests:
        plan = plan_voyage(request, input_roots=(str(tmp_path),))
        for step in plan.steps:
            assert step.workflow in SUPPORTED_WORKFLOWS
            parsed = parse_job_payload(step.job, base_dir=tmp_path)
            validate_workflow_parameters(parsed)
            assert parsed.action_mode.value == "dry_run"
            assert parsed.privacy_mode.value == "local_only"
            assert parsed.model_budget_usd == 0


def test_chained_steps_read_the_previous_output(tmp_path) -> None:
    plan = plan_voyage(
        "bündle die unterlagen und analysiere sie, dann erstelle einen bericht",
        input_roots=(str(tmp_path),),
    )

    workflows = [step.workflow for step in plan.steps]
    assert workflows == ["bundle_export", "evidence_analyst", "report_studio"]
    bundle, analyst, report = plan.steps
    assert bundle.reads_previous_step is False
    assert analyst.reads_previous_step is True
    assert analyst.job["input_roots"] == [bundle.job["output_dir"]]
    assert report.reads_previous_step is True
    assert report.job["input_roots"] == [analyst.job["output_dir"]]


def test_unmatched_request_says_so_instead_of_guessing() -> None:
    plan = plan_voyage("wie ist das wetter morgen in bernau")

    assert plan.steps == ()
    assert plan.unavailable == ()
    assert plan.matched is False
    assert any("could not be matched" in note for note in plan.notes)
    assert any("Command Bridge" in note for note in plan.notes)


def test_missing_root_becomes_a_question_rather_than_a_guess() -> None:
    plan = plan_voyage("bündle die unterlagen")

    step = plan.steps[0]
    assert step.job["input_roots"] == []
    assert "Which approved folder should this step read?" in step.questions_to_user
    assert any("No approved folder was named" in note for note in plan.notes)


@pytest.mark.parametrize(
    "text",
    ["", "   ", "x" * 2001],
    ids=["empty", "blank", "too-long"],
)
def test_request_text_is_bounded(text: str) -> None:
    with pytest.raises(ValueError):
        plan_voyage(text)


def test_plan_serializes_with_its_honest_flags(tmp_path) -> None:
    payload = plan_to_primitive(plan_voyage(ACCIDENT_REQUEST, input_roots=(str(tmp_path),)))

    assert payload["schema"] == VOYAGE_SCHEMA
    assert payload["executed"] is False
    assert payload["cloud_proof"] is False
    assert payload["matched"] is True
    assert all(step["job"]["action_mode"] == "dry_run" for step in payload["steps"])


# Three further requests the user wrote himself (D-027), kept verbatim.
FACTS_REQUEST = (
    "Destilliere alle Fakten aus diesem Ordner, doppelt Vorkommendes streiche, "
    "Bericht als PDF auf meinem Desktop"
)
DAILY_REQUEST = (
    "Prüfe neue Files im Ordner, jeden Tag Tagesbericht mit Dateinamen, Kurzinhalt, "
    "Einsteller-Benutzer"
)
TELEGRAM_REQUEST = (
    "Finde den Kontakt zu meiner Auslandskrankenversicherung und schreib sie mir in Telegram"
)


def test_facts_request_ends_in_a_real_pdf_report(tmp_path) -> None:
    plan = plan_voyage(FACTS_REQUEST, input_roots=(str(tmp_path),))

    # Since wave 1 activated fact_distill, this request runs on the active path
    # instead of being approximated by an analysis run.
    workflows = [step.workflow for step in plan.steps]
    # Fact Distill writes every requested format itself, and report_studio only
    # renders a verified analysis JSON, which Fact Distill does not produce - so
    # a second export step would be a promise the run could not keep.
    assert workflows == ["fact_distill"]
    assert plan.steps[0].job["parameters"]["dedupe_scope"] == "normalized"
    assert any("no separate Report Studio step" in note for note in plan.notes)

    report = plan.steps[-1]
    assert report.job["parameters"]["formats"] == ["pdf", "md"]

    # A desktop is a location outside the approved roots until it is approved.
    location = " ".join(report.questions_to_user)
    assert "approved folder should receive the file" in location
    assert "never writes outside them" in location

    # Striking repeated statements is active now, so nothing is declared missing.
    assert plan.unavailable == ()

    # Only duplicate FILES remain a planned service, and the wording says which
    # of the two readings is already handled.
    files = plan_voyage("finde doppelte dateien im ordner", input_roots=(str(tmp_path),))
    duplicates = next(item for item in files.unavailable if item.key == "duplicate_review")
    assert "duplicate FILES is a planned Document Service" in duplicates.reason
    assert "Fact Distill strikes them" in duplicates.reason


def test_daily_report_request_names_the_missing_uploader_field(tmp_path) -> None:
    plan = plan_voyage(DAILY_REQUEST, input_roots=(str(tmp_path),))

    # File name and short content are what Folder Digest already produces.
    assert [step.workflow for step in plan.steps] == ["folder_digest"]

    uploader = next(item for item in plan.unavailable if item.key == "uploader_attribution")
    assert "not the account that placed a file" in uploader.reason
    assert "planned extension" in uploader.reason
    assert "guessed author would be worse than none" in uploader.reason
    assert uploader.alternative_workflows == ("folder_digest",)

    # "jeden Tag" is a repetition request and gets the two honest answers.
    assert plan.recurring is not None
    assert len(plan.recurring.options) == 2
    assert "no scheduler of its own" in plan.recurring.message


def test_telegram_request_prepares_a_draft_and_refuses_the_channel(tmp_path) -> None:
    plan = plan_voyage(TELEGRAM_REQUEST, input_roots=(str(tmp_path),))

    workflows = [step.workflow for step in plan.steps]
    assert "contact_monitor" in workflows
    assert workflows[-1] == "controlled_email"

    chat = next(item for item in plan.unavailable if item.key == "chat_delivery")
    assert "no chat delivery" in chat.reason
    assert "would be a claim, not a feature" in chat.reason
    assert chat.alternative_workflows == ("controlled_email",)
    assert "forward it from the app you already use" in chat.approximation


def test_checking_a_folder_is_not_mistaken_for_an_evidence_analysis(tmp_path) -> None:
    # "prüfe" alone is too generic to mean an evidence run; the digest answers it.
    plan = plan_voyage("Prüfe neue Files im Ordner", input_roots=(str(tmp_path),))
    assert [step.workflow for step in plan.steps] == ["folder_digest"]

    # The specific evidence words still route to the analyst.
    analysis = plan_voyage("prüfe die verträge auf widersprüche", input_roots=(str(tmp_path),))
    assert "evidence_analyst" in [step.workflow for step in analysis.steps]
