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
