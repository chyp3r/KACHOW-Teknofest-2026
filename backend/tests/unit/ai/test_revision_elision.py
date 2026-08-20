"""Unit tests for detect_content_loss -- the deterministic check that
catches a reviser eliding real (already-filled-in) content with an
ellipsis/shorthand instead of reproducing it verbatim, on the two revise
paths (a whole-draft rewrite, any repair pass) that don't splice through
`_merge` and so have no other structural guarantee against it.
"""

from app.ai.revision.elision import detect_content_loss

PREVIOUS_DRAFT = (
    "Sayı: E-123-456\n"
    "Tarih: 30.07.2026\n"
    "Konu: Yıllık İzin Talebi\n\n"
    "Sayın Ahmet Yılmaz,\n\n"
    "İlgi yazı kapsamında 15-20 Ağustos 2026 tarihleri arasında yıllık izin "
    "kullanmak istediğimi arz ederim.\n\n"
    "Arz ederim.\n\n"
    "Mehmet Öztürk\nGenel Müdür"
)


def test_a_faithful_rewrite_is_not_flagged():
    rewritten = PREVIOUS_DRAFT.replace("Arz ederim.\n\n", "Bilgilerinize sunarım.\n\n", 1)
    assert detect_content_loss(PREVIOUS_DRAFT, rewritten, "kapanışı değiştir") is None


def test_an_ellipsis_standing_in_for_dropped_content_is_flagged():
    rewritten = (
        "Sayı: E-123-456\nTarih: 30.07.2026\nKonu: Yıllık İzin Talebi\n\n"
        "...\n\nBilgilerinize sunarım.\n\nMehmet Öztürk\nGenel Müdür"
    )
    finding = detect_content_loss(PREVIOUS_DRAFT, rewritten, "kapanışı değiştir")
    assert finding is not None
    assert "..." in finding.detail or "…" in finding.detail


def test_a_bracketed_unchanged_marker_is_flagged():
    rewritten = "Sayı: E-123-456\n\n[değişmedi]\n\nArz ederim.\n\nMehmet Öztürk"
    finding = detect_content_loss(PREVIOUS_DRAFT, rewritten, "tarihi düzelt")
    assert finding is not None


def test_a_large_unexplained_shrink_is_flagged_even_without_a_marker():
    rewritten = "Sayın Ahmet Yılmaz,\n\nArz ederim.\n\nMehmet Öztürk"
    finding = detect_content_loss(PREVIOUS_DRAFT, rewritten, "kapanışı değiştir")
    assert finding is not None
    assert "içerik kaybı" in finding.detail.lower() or "kısaltma" in finding.detail.lower()


def test_an_explicit_shortening_instruction_permits_the_same_shrink():
    rewritten = "Sayın Ahmet Yılmaz,\n\nArz ederim.\n\nMehmet Öztürk"
    assert detect_content_loss(PREVIOUS_DRAFT, rewritten, "metni kısalt") is None


def test_an_empty_previous_draft_has_nothing_to_lose():
    assert detect_content_loss("", "Yeni bir taslak metni burada.", "") is None


# ==========================================
# Explicit deletion instructions (the "revizyon talimatımı dinlemedi" bug):
# a user asking to delete/remove a part must not have that deletion flagged
# as accidental content loss and looped back into a repair pass that tells
# the reviser to restore "already-filled" content -- see this module's own
# docstring on _SHORTENING_KEYWORDS.
# ==========================================
def test_an_explicit_deletion_instruction_permits_the_same_shrink():
    rewritten = "Sayın Ahmet Yılmaz,\n\nArz ederim.\n\nMehmet Öztürk"
    assert detect_content_loss(PREVIOUS_DRAFT, rewritten, "ikinci paragraftan bir kısmı sil") is None


def test_a_removal_verb_instruction_permits_the_same_shrink():
    rewritten = "Sayın Ahmet Yılmaz,\n\nArz ederim.\n\nMehmet Öztürk"
    assert detect_content_loss(PREVIOUS_DRAFT, rewritten, "izin tarihleri kısmını çıkar") is None


def test_a_kaldir_verb_instruction_permits_the_same_shrink():
    rewritten = "Sayın Ahmet Yılmaz,\n\nArz ederim.\n\nMehmet Öztürk"
    assert detect_content_loss(PREVIOUS_DRAFT, rewritten, "bu cümleyi kaldır") is None


def test_a_temizle_verb_instruction_permits_the_same_shrink():
    rewritten = "Sayın Ahmet Yılmaz,\n\nArz ederim.\n\nMehmet Öztürk"
    assert detect_content_loss(PREVIOUS_DRAFT, rewritten, "ikinci paragrafı temizle") is None


def test_an_azalt_verb_instruction_permits_the_same_shrink():
    rewritten = "Sayın Ahmet Yılmaz,\n\nArz ederim.\n\nMehmet Öztürk"
    assert detect_content_loss(PREVIOUS_DRAFT, rewritten, "gövde metnini azalt") is None


# ==========================================
# C10: "sil" must not misfire as a substring of an unrelated word, and a
# negated shortening instruction must not be read as a request for one.
# ==========================================
def test_asil_metni_koru_does_not_misfire_as_a_deletion_instruction():
    """"Asıl metni koru" folds to "asil metni koru" -- "sil" is a bare
    substring of "asil", not the word "sil" ("delete"). Before the
    word-boundary fix, this let a *content-preservation* instruction
    silently permit real content loss."""
    rewritten = "Sayın Ahmet Yılmaz,\n\nArz ederim.\n\nMehmet Öztürk"
    finding = detect_content_loss(PREVIOUS_DRAFT, rewritten, "asıl metni koru")
    assert finding is not None


def test_a_negated_shortening_instruction_does_not_permit_the_shrink():
    """"Hiçbir yeri kısaltma" contains "kisalt" but is an explicit
    instruction *not* to shorten -- the opposite of what an unqualified
    substring hit on "kisalt" would suggest."""
    rewritten = "Sayın Ahmet Yılmaz,\n\nArz ederim.\n\nMehmet Öztürk"
    finding = detect_content_loss(PREVIOUS_DRAFT, rewritten, "hiçbir yeri kısaltma")
    assert finding is not None


# ==========================================
# C11: the elision marker check is a delta against the previous draft, not
# an absolute search over the rewrite -- a "..." the previous draft already
# legitimately carried must not re-trigger on every subsequent pass that
# never touched it.
# ==========================================
def test_a_pre_existing_ellipsis_untouched_by_this_pass_is_not_flagged():
    previous = PREVIOUS_DRAFT.replace(
        "Sayın Ahmet Yılmaz,", "İlgi: [E-1... sayılı] yazınız.\n\nSayın Ahmet Yılmaz,"
    )
    rewritten = previous.replace("Arz ederim.\n\n", "Bilgilerinize sunarım.\n\n", 1)
    assert detect_content_loss(previous, rewritten, "kapanışı değiştir") is None


def test_a_newly_introduced_ellipsis_is_still_flagged():
    previous = PREVIOUS_DRAFT.replace(
        "Sayın Ahmet Yılmaz,", "İlgi: [E-1... sayılı] yazınız.\n\nSayın Ahmet Yılmaz,"
    )
    rewritten = (
        "İlgi: [E-1... sayılı] yazınız.\n\nSayın Ahmet Yılmaz,\n\n...\n\n"
        "Bilgilerinize sunarım.\n\nMehmet Öztürk\nGenel Müdür"
    )
    finding = detect_content_loss(previous, rewritten, "kapanışı değiştir")
    assert finding is not None
