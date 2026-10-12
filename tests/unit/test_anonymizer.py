from __future__ import annotations

import itertools
import re

from nemofold.anonymizer import (
    _EXEMPT,
    PATTERNS,
    _is_date,
    _minutes_prefix,
    detect_sensitive_categories,
    pseudonymize_text,
)


def test_pseudonymizer_removes_common_identifiers_and_explicit_terms() -> None:
    text = (
        "Lukas Example uses lukas@example.org and +49 171 1234567. "
        "File C:\\Users\\lukas\\private\\case.txt; IBAN DE89 3704 0044 0532 0130 00."
    )

    result = pseudonymize_text(text, sensitive_terms=("Lukas Example",))

    assert "Lukas Example" not in result.text
    assert "lukas@example.org" not in result.text
    assert "+49 171 1234567" not in result.text
    assert "C:\\Users\\lukas" not in result.text
    assert "DE89 3704" not in result.text
    assert "<TERM_001>" in result.text
    assert "<EMAIL_001>" in result.text
    assert "<PHONE_001>" in result.text
    assert "<PATH_001>" in result.text
    assert "<IBAN_001>" in result.text
    assert result.replacement_counts == {
        "EMAIL": 1,
        "IBAN": 1,
        "PATH": 1,
        "PHONE": 1,
        "TERM": 1,
    }


def test_pseudonymizer_is_deterministic_and_does_not_store_original_values() -> None:
    first = pseudonymize_text("a@example.org then a@example.org")
    second = pseudonymize_text("a@example.org then a@example.org")

    assert first == second
    assert first.text == "<EMAIL_001> then <EMAIL_001>"
    assert "a@example.org" not in repr(first)


def test_dates_stay_readable_while_phone_and_case_numbers_are_masked() -> None:
    # Endabnahme 2026-10-12: every date was masked as PHONE, so a cloud
    # timeline question arrived without a single date.
    text = (
        "Am Samstag, 14.03.2026, gegen 21:30 Uhr. Annahme: 13.03.2026 17:00. "
        "ISO 2026-03-14. Police KV-2026-0447. Ruf 0761 1234567 oder +49 171 1234567, "
        "am 01.03.2026: 0761/987654."
    )

    result = pseudonymize_text(text)

    for date in ("14.03.2026", "13.03.2026 17:00", "2026-03-14", "01.03.2026"):
        assert date in result.text, date
    for secret in ("0761 1234567", "+49 171 1234567", "0761/987654", "2026-0447"):
        assert secret not in result.text, secret
    assert result.replacement_counts == {"PHONE": 4}


def test_a_date_never_frees_the_digits_around_it() -> None:
    # Independent review R4 (Codex): a first date exemption let these through
    # unmasked and unflagged. The PHONE pattern is the original one again; only
    # a run that is exactly one calendar-valid date is exempt.
    leaks = [
        "14.03.2026-01711234567",
        "2026-03-14-01711234567",
        "2026-03-14.01711234567",
        "Tel. 0761-12-30",
        "Police KV-2026-03-14-1234",
        "31.02.2026",
        "29.02.2025",
        "2026-02-31",
        "0000-01-01",
        "01.12.1234567",
        "14.03.2026 99",
    ]
    for text in leaks:
        assert "PHONE" in detect_sensitive_categories(text), text
        assert pseudonymize_text(text).replacement_counts.get("PHONE") == 1, text
    for text in ("Am 14.03.2026.", "Leap day 29.02.2024 ok", "um 13.03.2026 17:00 Uhr",
                 "(14.03.2026)"):
        assert detect_sensitive_categories(text) == (), text
        assert pseudonymize_text(text).text == text, text


def test_masked_text_passes_the_residual_check_and_times_need_real_minutes() -> None:
    # Review R5 (Codex): after masking, "14.03.2026-<PHONE_001>" was flagged
    # again and blocked the context; and "17:abc" counted as a time.
    for text in ("14.03.2026-01711234567", "2026-03-14/01711234567", "Am 14.03.2026. 0761 1234567"):
        masked = pseudonymize_text(text).text
        assert "<PHONE_001>" in masked, text
        assert detect_sensitive_categories(masked) == (), masked
    for text in ("14.03.2026 17:abc", "14.03.2026 17:99", "14.03.2026 17.:00", "14.03.2026 17"):
        assert "PHONE" in detect_sensitive_categories(text), text


def test_runs_longer_than_any_cap_leave_no_readable_tail() -> None:
    # Review R6 (Codex): a cap of 64 digits moved the split and left "987654"
    # readable after sixteen four-digit groups.
    for groups in (16, 17, 40):
        result = pseudonymize_text("1234 " * groups + "987654")
        assert "987654" not in result.text, groups
        assert result.replacement_counts == {"PHONE": 1}, groups
        assert detect_sensitive_categories(result.text) == ()


def test_unicode_minutes_keep_a_date_with_its_time() -> None:
    # Review R6-02: [0-5] accepted only ASCII minutes.
    for text in ("14.03.2026 23:\u0660\u0660", "14.03.2026 23:\uff10\uff10"):
        assert pseudonymize_text(text).text == text
    assert "PHONE" in detect_sensitive_categories("14.03.2026 23:\u0666\u0660")


def test_a_long_digit_run_is_masked_as_a_whole() -> None:
    # Review R5-B01 (pre-existing): a cap of 15 digits split long runs and a
    # remainder under seven digits stayed readable.
    result = pseudonymize_text("am 01.03.2026 0761/987654 und 1234 5678 9012 3456 7890 12")

    assert "987654" not in result.text
    assert "7890 12" not in result.text
    assert detect_sensitive_categories(result.text) == ()


def test_time_minutes_stay_and_the_number_after_them_is_masked() -> None:
    text = "13.03.2026 17:00 0761 1234567"
    masked = pseudonymize_text(text).text

    assert masked == "13.03.2026 17:00 <PHONE_001>"
    assert detect_sensitive_categories(masked) == ()
    # minutes are never a way around the mask (a rejected guard leaked these)
    assert "154191" not in pseudonymize_text("9263428960:34.154191").text


def test_every_digit_the_original_pattern_masked_is_still_masked() -> None:
    # Property from review rounds R4-R6: apart from exact dates and the two
    # minute digits of a clock time, nothing the pre-2026-10-12 pattern masked
    # may become readable, and masked text never trips the residual check.
    original = re.compile(r"(?<!\w)(?:\+\d{1,3}[ .()/\-]*)?(?:\d[ .()/\-]*){7,15}(?!\w)")
    phone = dict(PATTERNS)["PHONE"]
    for sep, width, count, tail in itertools.product(
        (" ", ".", "-", "/", "(", ")"), range(1, 9), range(1, 13), ("", " 9", " 987", " 987654")
    ):
        text = "Contact " + sep.join(["12345678"[:width]] * count) + tail + " end"
        before = {
            index
            for match in original.finditer(text)
            for index in range(match.start(), match.end())
            if text[index].isdigit()
        }
        masked, allowed = set(), set()
        for match in phone.finditer(text):
            digits = {i for i in range(match.start(), match.end()) if text[i].isdigit()}
            if _is_date(match):
                allowed |= digits
            elif not _EXEMPT["PHONE"](match):
                kept = match.start() + _minutes_prefix(match)
                allowed |= {i for i in digits if i < kept}
                masked |= {i for i in digits if i >= kept}
        assert before <= masked | allowed, text
        assert detect_sensitive_categories(pseudonymize_text(text).text) == (), text
