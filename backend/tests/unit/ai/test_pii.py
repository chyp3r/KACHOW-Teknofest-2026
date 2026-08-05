"""Unit tests for deterministic Turkish PII detection."""

import pytest

from app.ai.guardrails.pii import find_pii

#: A real checksum-valid TCKN (not a live person's -- generated from the
#: algorithm itself, the same way the module validates one).
VALID_TCKN = "12345678950"
#: Same digits, last check digit off by one -- fails the mod-10 check.
INVALID_TCKN_CHECKSUM = "12345678951"
#: A real checksum-valid Turkish IBAN.
VALID_IBAN = "TR620001001234567890123456"


def _kinds(findings):
    return {finding.kind for finding in findings}


# ==========================================
# TCKN
# ==========================================
def test_finds_a_checksum_valid_tckn():
    findings = find_pii(f"Başvuran T.C. Kimlik No: {VALID_TCKN} olan kişidir.")
    assert "tckn" in _kinds(findings)
    tckn_finding = next(f for f in findings if f.kind == "tckn")
    assert VALID_TCKN not in tckn_finding.preview
    assert tckn_finding.preview.startswith(VALID_TCKN[:2])
    assert tckn_finding.preview.endswith(VALID_TCKN[-2:])


def test_rejects_an_11_digit_number_with_a_bad_checksum():
    """An 11-digit document/reference number must not false-positive as a
    TCKN just because it happens to be the right length."""
    findings = find_pii(f"Belge referans numarası: {INVALID_TCKN_CHECKSUM}")
    assert "tckn" not in _kinds(findings)


def test_does_not_match_an_11_digit_substring_of_a_longer_number():
    findings = find_pii(f"Referans: 9{VALID_TCKN}9")
    assert "tckn" not in _kinds(findings)


# ==========================================
# IBAN
# ==========================================
def test_finds_a_checksum_valid_iban():
    findings = find_pii(f"Ödeme için IBAN: {VALID_IBAN} kullanılacaktır.")
    assert "iban" in _kinds(findings)
    iban_finding = next(f for f in findings if f.kind == "iban")
    assert VALID_IBAN not in iban_finding.preview


def test_rejects_a_tr_prefixed_string_with_a_bad_checksum():
    bogus = "TR000001001234567890123456"
    findings = find_pii(f"IBAN: {bogus}")
    assert "iban" not in _kinds(findings)


def test_iban_matches_with_space_grouping_as_banks_print_it():
    spaced = " ".join(VALID_IBAN[i : i + 4] for i in range(0, len(VALID_IBAN), 4))
    findings = find_pii(f"IBAN: {spaced}")
    assert "iban" in _kinds(findings)


# ==========================================
# Phone
# ==========================================
def test_finds_a_phone_number_with_a_telefon_label_at_high_confidence():
    findings = find_pii("Telefon: 0532 123 45 67")
    phone_findings = [f for f in findings if f.kind == "telefon"]
    assert phone_findings
    assert phone_findings[0].confidence >= 0.8


def test_finds_a_bare_phone_shaped_number_at_lower_confidence():
    findings = find_pii("İletişim için 0532 123 45 67 numarasını arayınız.")
    phone_findings = [f for f in findings if f.kind == "telefon"]
    assert phone_findings
    assert phone_findings[0].confidence < 0.8


# ==========================================
# Address
# ==========================================
def test_finds_an_address_line_with_multiple_keywords():
    findings = find_pii("Adres: Atatürk Mahallesi İnönü Caddesi No: 12 Kat: 3")
    assert "adres" in _kinds(findings)


def test_address_preview_never_leaks_the_raw_line():
    """Regression: `_mask(..., keep_end=0)` used to slice `value[-0:]`,
    which is Python for "the whole string" rather than "nothing" -- the
    masked preview silently contained the full raw address."""
    line = "Adres: Atatürk Mahallesi İnönü Caddesi No: 12 Kat: 3"
    findings = find_pii(line)
    address_finding = next(f for f in findings if f.kind == "adres")
    assert line not in address_finding.preview
    assert "Atatürk" not in address_finding.preview
    assert "İnönü" not in address_finding.preview


def test_a_single_incidental_word_is_not_an_address():
    findings = find_pii("Bu konuda bir sokak röportajı yapıldı.")
    assert "adres" not in _kinds(findings)


# ==========================================
# General
# ==========================================
def test_empty_text_finds_nothing():
    assert find_pii("") == []


def test_clean_official_text_finds_nothing():
    text = "T.C.\nÖRNEK BAKANLIĞI\nSayı: E-123\nKonu: İzin Talebi\nSaygılarımla."
    assert find_pii(text) == []
