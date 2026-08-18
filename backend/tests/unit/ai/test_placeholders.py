"""Unit tests for the "not found" marker -> [...] placeholder backstop.

The brief tells the writer to leave a `[...]` placeholder for anything
missing, but a smaller local model can still write the literal word instead
-- these tests prove the deterministic backstop catches that and produces
text `PLACEHOLDER_PATTERN`/`build_missing_info_request` can actually see.
"""

from app.ai.verification.draft_verifier import PLACEHOLDER_PATTERN
from app.ai.verification.missing_info import build_missing_info_request
from app.ai.verification.placeholders import (
    fill_date_placeholders,
    normalize_role_placeholders,
    normalize_unfilled_markers,
)


def test_a_literal_bulunamadi_value_becomes_a_named_placeholder():
    draft = "Konu: İzin Talebi\nSayı: Bulunamadı\nTarih: 30.07.2026\n\nSayın Makam,"

    normalized, count = normalize_unfilled_markers(draft)

    assert "Sayı: [Belge Sayısı]" in normalized
    assert "Bulunamadı" not in normalized
    assert count == 1


def test_every_recognised_field_gets_its_own_placeholder_name():
    draft = (
        "Konu: Bulunamadı\n"
        "Sayı: bulunamadı\n"
        "Tarih: belirtilmemiş\n"
        "Muhatap: bilinmiyor\n\n"
        "Sayın Makam,"
    )

    normalized, count = normalize_unfilled_markers(draft)

    assert "Konu: [Konu]" in normalized
    assert "Sayı: [Belge Sayısı]" in normalized
    assert "Tarih: [Tarih]" in normalized
    assert "Muhatap: [Muhatap]" in normalized
    assert count == 4


def test_various_unfilled_marker_spellings_are_all_recognised():
    for marker in ("Bulunamadı", "Belirtilmemiş", "Yok", "N/A", "---", "Mevcut Değil"):
        draft = f"Tarih: {marker}\n\nSayın Makam,"
        normalized, count = normalize_unfilled_markers(draft)
        assert count == 1, marker
        assert "Tarih: [Tarih]" in normalized, marker


def test_a_genuinely_filled_field_is_left_untouched():
    draft = "Konu: Yıllık İzin Talebi\nSayı: E-123-456\nTarih: 30.07.2026\n\nSayın Makam,"

    normalized, count = normalize_unfilled_markers(draft)

    assert normalized == draft
    assert count == 0


def test_an_already_correct_placeholder_is_left_untouched():
    draft = "Sayı: [Belge Sayısı]\nTarih: [Tarih]\n\nSayın Makam,"

    normalized, count = normalize_unfilled_markers(draft)

    assert normalized == draft
    assert count == 0


def test_an_ilgi_line_quoting_another_document_is_not_a_recognised_field():
    """Only the draft's own Sayı/Tarih/Konu/Muhatap header lines are
    recognised -- an "İlgi:" line is a different label entirely and must
    never be touched by this backstop."""
    draft = "İlgi: Bulunamadı sayılı yazınız.\n\nSayın Makam,"

    normalized, count = normalize_unfilled_markers(draft)

    assert normalized == draft
    assert count == 0


def test_the_normalized_placeholder_is_picked_up_as_a_missing_info_question():
    """The whole point: once normalized, the standard missing-information
    pipeline (already wired to PLACEHOLDER_PATTERN) asks the human instead
    of silently shipping the literal word."""
    draft = "Konu: Yıllık İzin Talebi\nSayı: Bulunamadı\nTarih: 30.07.2026\n\nSayın Makam,"

    normalized, _ = normalize_unfilled_markers(draft)

    assert PLACEHOLDER_PATTERN.search(normalized)
    questions = build_missing_info_request(normalized, report=None, classification={})
    assert any(question.key == "belge_sayisi" for question in questions)


def test_the_draft_own_date_placeholder_is_filled_with_the_server_resolved_date():
    """The user must never be asked what today's date is -- the draft's own
    "Tarih:" line is filled deterministically instead."""
    draft = "Konu: Yıllık İzin Talebi\nSayı: [Belge Sayısı]\nTarih: [Tarih]\n\nSayın Makam,"

    filled, count = fill_date_placeholders(draft, "18.08.2026")

    assert "Tarih: 18.08.2026" in filled
    assert count == 1
    assert "Sayı: [Belge Sayısı]" in filled


def test_a_verbose_date_placeholder_is_also_filled():
    draft = "Tarih: [Tarih Eksik - Lütfen Doldurun]\n\nSayın Makam,"

    filled, count = fill_date_placeholders(draft, "18.08.2026")

    assert filled == "Tarih: 18.08.2026\n\nSayın Makam,"
    assert count == 1


def test_an_ilgi_line_referencing_the_incoming_document_date_is_left_alone():
    """The Tarih: label is the response's own field only -- a reference to
    the incoming document's date (in the İlgi line) must never be
    overwritten with today's date."""
    draft = "İlgi: [Gelen Evrak Tarihi] sayılı yazınız.\nTarih: [Tarih]\n\nSayın Makam,"

    filled, count = fill_date_placeholders(draft, "18.08.2026")

    assert "İlgi: [Gelen Evrak Tarihi] sayılı yazınız." in filled
    assert "Tarih: 18.08.2026" in filled
    assert count == 1


def test_no_today_value_leaves_the_placeholder_untouched():
    draft = "Tarih: [Tarih]\n\nSayın Makam,"

    filled, count = fill_date_placeholders(draft, "")

    assert filled == draft
    assert count == 0


def test_a_missing_info_request_never_asks_about_the_date():
    """Defense in depth: even if a date placeholder somehow survives to
    build_missing_info_request, it must never turn into a question."""
    draft = "Konu: İzin Talebi\nTarih: [Tarih]\n\nSayın Makam,"

    questions = build_missing_info_request(draft, report=None, classification={})

    assert not any("tarih" in question.key for question in questions)


# ==========================================
# normalize_role_placeholders
# ==========================================
def test_bare_signature_placeholders_are_attributed_to_the_signing_official():
    draft = "Arz ederim.\n\n[Ad Soyad]\n[Unvan]"

    normalized, count = normalize_role_placeholders(draft)

    assert "[İmzalayacak yetkilinin adı ve soyadı]" in normalized
    assert "[İmzalayacak yetkilinin unvanı]" in normalized
    assert "[Ad Soyad]" not in normalized
    assert "[Unvan]" not in normalized
    assert count == 2


def test_accent_and_casing_variants_of_unvan_are_all_recognised():
    for variant in ("Ünvan", "UNVAN", "ünvan"):
        normalized, count = normalize_role_placeholders(f"[{variant}]")
        assert normalized == "[İmzalayacak yetkilinin unvanı]", variant
        assert count == 1, variant


def test_a_bare_imza_placeholder_becomes_the_signing_officials_name():
    normalized, count = normalize_role_placeholders("[İmza]")
    assert normalized == "[İmzalayacak yetkilinin adı ve soyadı]"
    assert count == 1


def test_a_bare_institution_placeholder_is_attributed_to_the_sender():
    normalized, count = normalize_role_placeholders("T.C.\n[Kurum Adı]\nSayı: [Belge Sayısı]")
    assert "[Gönderen kurumun adı]" in normalized
    assert count == 1


def test_an_individual_petition_attributes_the_signature_to_the_petitioner_instead():
    draft = "Gereğini arz ederim.\n\n[Ad Soyad]\n[Unvan]"

    normalized, count = normalize_role_placeholders(draft, is_individual_petition=True)

    assert "[Dilekçe sahibinin adı ve soyadı]" in normalized
    assert "[Dilekçe sahibinin unvanı]" in normalized
    assert count == 2


def test_placeholders_that_already_state_a_role_are_left_untouched():
    draft = "[İmzalayacak yetkilinin adı ve soyadı]\n[Belge Sayısı]\n[Konu]"

    normalized, count = normalize_role_placeholders(draft)

    assert normalized == draft
    assert count == 0


def test_the_renamed_placeholder_reaches_missing_info_as_an_attributed_question():
    """The whole point: the human gate's question text comes straight from
    the placeholder label, so an unattributed '[Ad Soyad]' used to render
    as an unattributed "'Ad Soyad' bilgisi nedir?" question."""
    draft = "Arz ederim.\n\n[Ad Soyad]"

    normalized, _ = normalize_role_placeholders(draft)
    questions = build_missing_info_request(normalized, report=None, classification={})

    assert len(questions) == 1
    assert questions[0].label == "İmzalayacak yetkilinin adı ve soyadı"
