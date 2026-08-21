"""Unit tests for app.ai.verification.style_checks.

These are the deterministic register/consistency checks Faz 4 adds --
person-address consistency, repeated filler sentences, and a bare
placeholder label left unbracketed in the signature block. All three are
regex-only (no LLM), so these tests pin down both the positive (catches the
reported bug's shape) and negative (a well-formed draft is left alone) case
for each.
"""

from app.ai.verification.style_checks import (
    check_filler_sentences,
    check_meta_commentary,
    check_person_consistency,
    check_signature_block,
)


# ==========================================
# check_person_consistency
# ==========================================
def test_the_same_person_addressed_both_formally_and_informally_is_flagged():
    draft = (
        "Sayın Ahmet Yılmaz,\n\n"
        "Ahmet Bey'in stajı başarıyla tamamlanmıştır.\n\n"
        "Bilgilerinize sunulur."
    )

    findings = check_person_consistency(draft)

    assert len(findings) == 1
    assert findings[0].rule_id == "kisi_tutarsizligi"
    assert "Ahmet" in findings[0].detail


def test_a_single_consistent_address_form_is_not_flagged():
    draft = (
        "Sayın Ahmet Yılmaz,\n\n"
        "Talebiniz değerlendirilmiştir.\n\n"
        "Bilgilerinize sunulur."
    )

    assert check_person_consistency(draft) == []


def test_an_unrelated_bey_hanim_mention_with_no_matching_sayin_is_not_flagged():
    draft = (
        "Sayın Rektörlük,\n\n"
        "Ahmet Bey'in stajı başarıyla tamamlanmıştır.\n\n"
        "Bilgilerinize sunulur."
    )

    assert check_person_consistency(draft) == []


def test_the_same_person_is_only_flagged_once_even_with_repeated_mentions():
    draft = (
        "Sayın Ahmet Yılmaz,\n\n"
        "Ahmet Bey'in başvurusu incelenmiştir. Ahmet Bey'in talebi kabul edilmiştir.\n\n"
        "Bilgilerinize sunulur."
    )

    findings = check_person_consistency(draft)
    assert len(findings) == 1


# ==========================================
# check_filler_sentences
# ==========================================
def test_a_verbatim_repeated_sentence_is_flagged():
    draft = (
        "Konu: Staj Onayı\n\n"
        "Personelin stajı başarıyla ve eksiksiz olarak tamamlanmıştır. "
        "Diğer bir husus daha vardır. "
        "Personelin stajı başarıyla ve eksiksiz olarak tamamlanmıştır.\n\n"
        "Bilgilerinize sunulur."
    )

    findings = check_filler_sentences(draft)

    assert len(findings) == 1
    assert findings[0].rule_id == "dolgu_ifade"


def test_a_short_repeated_closing_formula_is_not_flagged():
    """Fewer than six significant tokens is exempt -- a short, intentionally
    formulaic phrase (the closing itself) is not padding."""
    draft = "Konu: X\n\nBilgilerinize sunulur.\n\nBilgilerinize sunulur."

    assert check_filler_sentences(draft) == []


def test_distinct_sentences_are_never_flagged():
    draft = (
        "Konu: Staj Onayı\n\n"
        "Personelin stajı başarıyla ve eksiksiz olarak tamamlanmıştır. "
        "Kendisi belirlenen tüm görevleri zamanında yerine getirmiştir.\n\n"
        "Bilgilerinize sunulur."
    )

    assert check_filler_sentences(draft) == []


def test_a_repeated_sentence_inside_a_placeholder_is_not_counted():
    draft = (
        "Konu: [BİLGİ EKSİK: Personelin stajı başarıyla ve eksiksiz olarak tamamlanmıştır.]\n\n"
        "Personelin stajı başarıyla ve eksiksiz olarak tamamlanmıştır.\n\n"
        "Bilgilerinize sunulur."
    )

    assert check_filler_sentences(draft) == []


# ==========================================
# check_signature_block
# ==========================================
def test_a_bare_unbracketed_meta_value_in_the_signature_block_is_flagged():
    draft = "Arz ederim.\n\nAd Soyad\nUnvan"

    findings = check_signature_block(draft)

    assert {finding.detail for finding in findings}
    assert len(findings) == 2
    assert all(finding.rule_id == "imza_blogu_uydurma" for finding in findings)


def test_a_real_filled_signature_is_not_flagged():
    draft = "Arz ederim.\n\nAyşe Kaya\nGenel Müdür"

    assert check_signature_block(draft) == []


def test_a_correctly_bracketed_placeholder_is_not_flagged():
    """The bracketed case is normalize_role_placeholders's job (see
    placeholders.py) -- this check only ever fires on the bare, unbracketed
    form that backstop cannot see."""
    draft = "Arz ederim.\n\n[İmzalayacak yetkilinin adı ve soyadı]\n[İmzalayacak yetkilinin unvanı]"

    assert check_signature_block(draft) == []


# ==========================================
# check_meta_commentary
# ==========================================
def test_the_reported_bugs_exact_phrasing_is_flagged():
    draft = "Konu: Staj Onayı\n\nSadece verilen kayıt incelenmiştir.\n\nBilgilerinize sunulur."

    findings = check_meta_commentary(draft)

    assert len(findings) == 1
    assert findings[0].rule_id == "meta_yorum"
    assert "incelenmiştir" in findings[0].detail


def test_a_wordier_variant_of_the_same_shape_is_flagged():
    draft = "Yalnızca sağlanan bilgiler doğrultusunda değerlendirilmiştir."

    findings = check_meta_commentary(draft)

    assert len(findings) == 1
    assert findings[0].rule_id == "meta_yorum"


def test_a_claim_grounded_to_a_named_request_is_not_flagged():
    """The verb alone ("incelenmiştir") is legitimate, formulaic official
    register -- only the self-referential "sadece/yalnızca verilen ..."
    shape this bug report's symptom took should ever trip the check."""
    draft = "Talebiniz 5018 sayılı Kanun kapsamında incelenmiştir."

    assert check_meta_commentary(draft) == []
