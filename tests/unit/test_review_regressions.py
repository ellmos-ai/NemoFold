"""Regression tests for defects found in the 2026-10 code review.

Each test pins one reproduced failure, so the fix cannot quietly come undone.
"""

from __future__ import annotations

import io
import json
import types
import zipfile
from pathlib import Path

import pytest

from nemofold.case_chronicle import ChronicleInput, execute_relation_model
from nemofold.corroboration import within
from nemofold.document_extract import _extract_docx, _VisibleHTML, _xml_paragraphs
from nemofold.job_io import JobFileError, load_job_file, parse_job_payload
from nemofold.nebius_token_factory import TokenFactoryConfig
from nemofold.primitives import (
    AggregationBudget,
    Anchor,
    AnchoredStatement,
    FieldSpec,
    aggregate_mapreduce,
    deduplicate,
    extract_fields,
    fingerprint,
)
from nemofold.report_verifier import verify_run_report
from nemofold.timeline import parse_times

WORD = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _job_payload(**overrides) -> dict:
    payload = {
        "schema": "nemofold.job.v1",
        "workflow": "folder_digest",
        "input_roots": ["docs"],
        "output_dir": "out",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #


def test_docx_drops_tracked_deletions_and_keeps_breaks_and_tabs() -> None:
    document = (
        f"<w:document {WORD}><w:body>"
        '<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="1"/></w:tabs></w:pPr>'
        '<w:r><w:t xml:space="preserve">Betrag: </w:t></w:r>'
        "<w:del><w:r><w:delText>5000</w:delText></w:r></w:del>"
        "<w:ins><w:r><w:t>500</w:t></w:r></w:ins><w:r><w:t> EUR</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Datum: 01.01.2026</w:t><w:br/><w:t>Name:</w:t><w:tab/>"
        "<w:t>Anna</w:t></w:r></w:p>"
        "</w:body></w:document>"
    ).encode()

    text = _xml_paragraphs(document, paragraph_names=frozenset({"p"}))

    assert text == "Betrag: 500 EUR\nDatum: 01.01.2026\nName:\tAnna"


def test_a_malformed_docx_part_is_an_unreadable_source_not_a_crash() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document")

    with pytest.raises(ValueError, match="malformed"):
        _extract_docx(buffer.getvalue(), "bad.docx")


def test_html_text_leaves_out_script_and_style() -> None:
    parser = _VisibleHTML()
    parser.feed(
        "<style>body{color:red}</style><script>var apiKey='x';</script><p>Hallo</p>"
    )

    assert parser.parts == ["Hallo"]


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #


def test_a_clock_time_is_not_lent_to_the_next_date() -> None:
    points = parse_times("Am 01.03.2026 um 09:15 kam er, am 02.03.2026 ging er.")

    assert [point.value for point in points] == ["2026-03-01T09:15", "2026-03-02"]


def test_mixed_spellings_keep_written_order() -> None:
    points = parse_times("vom 2026-03-01 bis 05.03.2026")

    assert [point.value for point in points] == ["2026-03-01", "2026-03-05"]


def test_impossible_dates_and_hours_are_not_points() -> None:
    assert parse_times("am 31.02.2026 oder 39.19.2026") == ()
    assert [point.value for point in parse_times("um 25:10 am 01.03.2026")] == ["2026-03-01"]


def test_a_preceding_clock_time_still_counts() -> None:
    points = parse_times("Um 21:30 am 03.03.2026 sah ich ihn.")

    assert [point.value for point in points] == ["2026-03-03T21:30"]


def test_closeness_uses_the_real_calendar_at_the_end_of_february() -> None:
    late = parse_times("28.02.2026 23:30")[0]
    early = parse_times("01.03.2026 00:30")[0]

    assert within(late, early, 120)


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #


def _statement(text: str, line: int, source: str = "s") -> AnchoredStatement:
    return AnchoredStatement(text=text, anchor=Anchor(source_id=source, line=line))


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Der Saldo betraegt -500 EUR.", "Der Saldo betraegt 500 EUR."),
        ("Dosis 5,000 mg täglich.", "Dosis 5.000 mg täglich."),
    ],
)
def test_normalized_dedupe_keeps_different_numbers_apart(first, second) -> None:
    assert fingerprint(first, "normalized") != fingerprint(second, "normalized")
    outcome = deduplicate((_statement(first, 1), _statement(second, 2)))

    assert len(outcome.kept) == 2


def test_normalized_dedupe_still_folds_punctuation_and_case() -> None:
    assert fingerprint("Die Frist endet am 30.04.2026!", "normalized") == fingerprint(
        "die Frist endet am 30.04.2026.", "normalized"
    )


def test_a_symbol_only_statement_is_kept_not_lost() -> None:
    outcome = deduplicate((_statement("—", 1),))

    assert [item.text for item in outcome.kept] == ["—"]
    assert outcome.struck == ()


def test_a_hyphenated_label_is_not_the_field() -> None:
    rows, _ = extract_fields(
        (("s", "s.txt"),),
        {"s": "Name-Zusatz: c/o Meier\nName: Anna Schmidt\n"},
        (FieldSpec("Name"),),
    )

    assert rows[0].values[0].value == "Anna Schmidt"


def test_a_spaced_dash_still_separates_a_label() -> None:
    rows, _ = extract_fields(
        (("s", "s.txt"),), {"s": "Name – Anna Schmidt\n"}, (FieldSpec("Name"),)
    )

    assert rows[0].values[0].value == "Anna Schmidt"


def test_the_anchor_total_survives_the_second_stage() -> None:
    statements = tuple(
        _statement("Ticket wurde geschlossen heute.", line) for line in range(1, 121)
    )

    outcome = aggregate_mapreduce(statements, budget=AggregationBudget(partition_size=120))
    single = aggregate_mapreduce(statements, budget=AggregationBudget(partition_size=7))

    for result in (outcome.results[0], single.results[0]):
        assert result.support == 120
        assert result.anchor_total == 120
        assert result.anchors_truncated


# --------------------------------------------------------------------------- #
# Privacy
# --------------------------------------------------------------------------- #


def test_the_pseudonymous_relation_report_names_nobody(tmp_path) -> None:
    job = types.SimpleNamespace(
        output_dir=str(tmp_path),
        parameters={
            "known_names": ["Anna Schmidt", "Peter Müller"],
            "pseudonymous": True,
            "formats": ["md"],
        },
    )
    text = "Anna Schmidt ist die Schwester von Peter Müller.\n"

    _, artifacts, _, _ = execute_relation_model(job, ChronicleInput(("s1",), {"s1": text}), "r1")

    for artifact in artifacts:
        body = Path(artifact.path).read_text(encoding="utf-8")
        assert "Schmidt" not in body and "Müller" not in body, artifact.path


def test_the_token_factory_key_stays_out_of_repr() -> None:
    config = TokenFactoryConfig(
        api_key="secret-key-value",
        input_price_usd_per_million=0.1,
        output_price_usd_per_million=0.2,
    )

    assert "secret-key-value" not in repr(config)


# --------------------------------------------------------------------------- #
# Job files and ledgers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("budget", [10**400, float("nan"), float("inf"), -1])
def test_an_unusable_budget_is_a_job_file_error(tmp_path, budget) -> None:
    with pytest.raises(JobFileError, match="model_budget_usd"):
        parse_job_payload(_job_payload(model_budget_usd=budget), base_dir=tmp_path)


def test_a_job_file_with_a_byte_order_mark_loads(tmp_path) -> None:
    path = tmp_path / "job.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(_job_payload()).encode())

    assert load_job_file(path).job.workflow == "folder_digest"


def test_a_job_file_that_is_not_utf8_is_a_job_file_error(tmp_path) -> None:
    path = tmp_path / "job.json"
    path.write_bytes(json.dumps(_job_payload()).replace("docs", "Müller").encode("latin-1"))

    with pytest.raises(JobFileError, match="UTF-8"):
        load_job_file(path)


@pytest.mark.parametrize(
    "parameters",
    [
        {"min_support": "x"},
        {"min_support": 1},
        {"min_support": True},
        {"max_patterns": -1},
        {"partition_size": 0},
        {"focus_terms": "Miete"},
    ],
)
def test_pattern_mining_bounds_are_checked_at_preview(tmp_path, parameters) -> None:
    with pytest.raises(JobFileError):
        parse_job_payload(
            _job_payload(workflow="pattern_mining", parameters=parameters), base_dir=tmp_path
        )


def test_an_undecodable_ledger_is_reported_invalid_not_raised(tmp_path) -> None:
    ledger = tmp_path / "bad.json"
    ledger.write_bytes(b"\xff\xfe\x00garbage")

    verification = verify_run_report(ledger)

    assert not verification.valid
    assert verification.errors == ("report_json_invalid",)
