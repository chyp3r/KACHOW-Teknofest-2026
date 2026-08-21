"""Guards the canonical forms against becoming lossy.

These functions exist to make two spellings of one fact compare equal. The
failure mode that matters is the opposite one: two spellings of *different*
facts collapsing onto the same canonical string, which would turn a fabricated
date or amount into a grounded one and defeat the whole verifier. Every
canonicaliser therefore has a paired "different values stay different" test, and
unparseable input must return None so the caller falls back to textual
comparison rather than acting on a guess.

The specific formats here are the ones the measured baseline flagged as false
positives (see evaluation/reports/all-baseline.md): "1 Mart 2026" against
"01.03.2026", "m. 11" against "Madde 11", "125.000 TL" against "125.000,00 TL".
"""

import pytest

from app.ai.verification.normalizers import (
    canonical_amount,
    canonical_date,
    canonical_document_number,
    canonical_for_kind,
    canonical_legislation,
)


@pytest.mark.parametrize(
    "written",
    [
        "12.03.2026", "12/03/2026", "12-03-2026", "12 Mart 2026", "12 mart 2026",
        "2026-03-12",
    ],
)
def test_canonical_date_folds_every_supported_spelling(written):
    assert canonical_date(written) == "2026-03-12"


def test_canonical_date_pads_single_digit_components():
    assert canonical_date("1.3.2026") == "2026-03-01"
    assert canonical_date("1 Mart 2026") == "2026-03-01"
    assert canonical_date("2026-03-1") == "2026-03-01"


def test_canonical_date_matches_iso_against_turkish_notation():
    """The exact bug this fixes: a source document's own extracted text
    ("Dates: 2026-04-09 to 2026-05-06") and a draft restating the same date
    in Turkish register ("09.04.2026") must ground each other."""
    assert canonical_date("2026-04-09") == canonical_date("09.04.2026")
    assert canonical_date("2026-04-09") == "2026-04-09"


def test_canonical_date_keeps_different_dates_distinct():
    """The safety property: normalisation must not merge two real dates."""
    assert canonical_date("12.03.2026") != canonical_date("13.03.2026")
    assert canonical_date("12.03.2026") != canonical_date("12.04.2026")
    assert canonical_date("03.12.2026") != canonical_date("12.03.2026")
    assert canonical_date("2026-04-09") != canonical_date("2026-05-06")
    assert canonical_date("2026-04-09") != canonical_date("09.05.2026")


@pytest.mark.parametrize(
    "written",
    ["", "yakında", "32.01.2026", "12.13.2026", "12 Foo 2026", "2026", "2026-13-01"],
)
def test_canonical_date_returns_none_rather_than_guessing(written):
    assert canonical_date(written) is None


@pytest.mark.parametrize(
    "written",
    [
        "E-44444444-841-77",
        "E-44444444/841/77",
        "E 44444444 841 77",
        "e-44444444-841-77",
    ],
)
def test_canonical_document_number_ignores_separator_style(written):
    assert canonical_document_number(written) == "e4444444484177"


def test_canonical_document_number_keeps_different_numbers_distinct():
    assert canonical_document_number("2024/512") != canonical_document_number("2024/513")


def test_canonical_document_number_rejects_values_without_digits():
    assert canonical_document_number("Sayı") is None
    assert canonical_document_number("") is None


@pytest.mark.parametrize(
    "written", ["125.000,00 TL", "125.000 TL", "125000 TL", "125.000,00 ₺"]
)
def test_canonical_amount_folds_turkish_separator_notation(written):
    assert canonical_amount(written) == "125000 TRY"


def test_canonical_amount_preserves_a_real_fraction():
    assert canonical_amount("125.000,50 TL") == "125000.5 TRY"
    assert canonical_amount("125.000,50 TL") != canonical_amount("125.000,00 TL")


def test_canonical_amount_separates_currencies():
    assert canonical_amount("100 TL") != canonical_amount("100 EUR")
    assert canonical_amount("100 USD") == "100 USD"
    assert canonical_amount("100 Dolar") == "100 USD"


def test_canonical_amount_returns_none_without_a_currency():
    assert canonical_amount("125.000,00") is None
    assert canonical_amount("bir miktar") is None


@pytest.mark.parametrize("written", ["madde 11", "Madde 11", "m. 11", "m.11", "m 11"])
def test_canonical_legislation_folds_article_citations(written):
    assert canonical_legislation(written) == "madde:11"


@pytest.mark.parametrize("written", ["4982 sayılı", "4982 sayili", "4982 SAYILI"])
def test_canonical_legislation_folds_law_citations(written):
    assert canonical_legislation(written) == "kanun:4982"


def test_canonical_legislation_keeps_laws_and_articles_in_separate_namespaces():
    """A draft citing article 4982 is not grounded by a source citing law 4982."""
    assert canonical_legislation("4982 sayılı") != canonical_legislation("madde 4982")


def test_canonical_legislation_returns_none_for_non_citations():
    assert canonical_legislation("kanun") is None
    assert canonical_legislation("11") is None


def test_canonical_for_kind_dispatches_and_declines_untyped_kinds():
    assert canonical_for_kind("tarih", "1 Mart 2026") == "2026-03-01"
    assert canonical_for_kind("tutar", "100 TL") == "100 TRY"
    assert canonical_for_kind("mevzuat", "m. 7") == "madde:7"
    assert canonical_for_kind("sayı", "E-1-2") == "e12"
    # Institution names are compared textually; there is no canonical form and
    # inventing one would be fuzzy matching on a value that needs judgement.
    assert canonical_for_kind("kurum", "Örnek Bakanlığı") is None
    assert canonical_for_kind("bilinmeyen", "x") is None
