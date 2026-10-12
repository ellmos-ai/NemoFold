from __future__ import annotations

from nemofold.anonymizer import pseudonymize_text


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
        "am 01.03.2026 0761/987654."
    )

    result = pseudonymize_text(text)

    for date in ("14.03.2026", "13.03.2026 17:00", "2026-03-14", "01.03.2026"):
        assert date in result.text, date
    for secret in ("0761 1234567", "+49 171 1234567", "0761/987654", "2026-0447"):
        assert secret not in result.text, secret
    assert result.replacement_counts == {"PHONE": 4}
