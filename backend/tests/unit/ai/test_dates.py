"""Unit tests for `app.ai.workflows.dates.extract_draft_date`.

`today_tr()` itself is a one-line `datetime.now(...)` call with nothing to
unit test beyond its format; the actual logic worth covering is
`extract_draft_date`, the revision-time fallback that must recover a
draft's own existing "Tarih:" value instead of the caller reaching for
`today_tr()` and silently overwriting a field the user never touched.
"""

from app.ai.workflows.dates import extract_draft_date


def test_extracts_the_filled_date_line():
    draft = "Konu: İzin Talebi\nSayı: E-1\nTarih: 30.07.2026\n\nSayın Makam,"
    assert extract_draft_date(draft) == "30.07.2026"


def test_returns_none_for_a_bracketed_placeholder():
    draft = "Konu: İzin Talebi\nSayı: E-1\nTarih: [Tarih]\n\nSayın Makam,"
    assert extract_draft_date(draft) is None


def test_returns_none_when_there_is_no_date_line_at_all():
    draft = "Konu: İzin Talebi\nSayı: E-1\n\nSayın Makam,"
    assert extract_draft_date(draft) is None


def test_is_case_and_whitespace_tolerant():
    draft = "  tarih   :   30.07.2026  "
    assert extract_draft_date(draft) == "30.07.2026"


def test_an_ilgi_line_referencing_a_different_date_is_not_mistaken_for_the_draft_date():
    draft = "İlgi: 15.03.2026 tarihli yazınız.\nTarih: 30.07.2026\n"
    assert extract_draft_date(draft) == "30.07.2026"


def test_empty_text_returns_none():
    assert extract_draft_date("") is None
