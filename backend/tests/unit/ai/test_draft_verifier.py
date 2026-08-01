"""Unit tests for the deterministic groundedness/structure verifier."""

from app.ai.verification.draft_verifier import (
    MIN_AUTOMATED_CONFIDENCE_SCORE,
    STRUCTURE_CHECKS,
    verify_draft,
)

WELL_FORMED_DRAFT = (
    "Konu: Yıllık İzin Talebi\n"
    "Sayı: E-123-456\n"
    "Tarih: 30.07.2026\n\n"
    "Sayın Makam,\n\n"
    "Arz ederim.\n\n"
    "Mehmet Öztürk\nGenel Müdür"
)


def test_fabricated_document_number_is_flagged():
    draft = WELL_FORMED_DRAFT.replace("E-123-456", "E-999-999")
    report = verify_draft(draft, source_document="Sayı: E-123-456 tarihli evrak.")

    kinds = {claim.kind for claim in report.unsupported_claims}
    assert "sayı" in kinds


def test_document_number_present_in_source_is_not_flagged():
    report = verify_draft(
        WELL_FORMED_DRAFT,
        source_document="Sayı: E-123-456, Tarih: 30.07.2026 tarihli evrak.",
    )

    assert report.unsupported_claims == []
    assert report.confidence_score == 100.0
    assert report.requires_human_approval is False


def test_institution_paraphrase_escape_hatch_via_token_overlap():
    """A draft that shortens 'Çevre ve Şehircilik İl Müdürlüğü' to 'Çevre İl
    Müdürlüğü' shares enough significant tokens (>=75%) with the source's
    fuller name that it must not be flagged as a fabricated institution --
    even though the words aren't contiguous in the source, so a plain
    substring check alone would miss it.

    The institution phrase is placed after lowercase words on purpose:
    INSTITUTION_PATTERN's leading capitalized-word group is greedy and spans
    newlines, so placed directly after WELL_FORMED_DRAFT's capitalized
    signature block it would instead swallow "Öztürk Genel Müdür Çevre İl"
    as one (wrong) match -- a separate, pre-existing regex quirk this test
    must not conflate with the escape hatch it's actually checking.
    """
    draft = (
        "Konu: Yıllık İzin Talebi\n"
        "Sayı: E-123-456\n"
        "Tarih: 30.07.2026\n\n"
        "Sayın Makam,\n\n"
        "Konuya ilişkin olarak yerel şubemiz Çevre İl Müdürlüğü'ne bilgi vermiştir.\n\n"
        "Arz ederim.\n\n"
        "Mehmet Öztürk\nGenel Müdür"
    )
    report = verify_draft(
        draft, source_document="...Çevre ve Şehircilik İl Müdürlüğü'nün yazısı üzerine..."
    )

    assert not any(claim.kind == "kurum" for claim in report.unsupported_claims)


def test_placeholders_are_excluded_from_grounding_audit_but_still_counted():
    draft = WELL_FORMED_DRAFT + "\n[İMZA SAHİBİNİN ADI] tarafından onaylanmıştır."
    report = verify_draft(
        draft, source_document="Sayı: E-123-456, Tarih: 30.07.2026 tarihli evrak."
    )

    # The bracketed placeholder's contents (a deliberate gap) must not be
    # audited as a fabricated claim, even though nothing grounds it.
    assert report.placeholder_count == 1
    assert report.unsupported_claims == []
    assert report.requires_human_approval is True


def test_each_structure_check_contributes_its_full_weight_when_missing():
    """A draft with none of the five structural markers must be penalised by
    the exact sum of every STRUCTURE_CHECKS weight, not a partial or capped
    amount."""
    bare_draft = "Bu metinde hiçbir resmi unsur yok."
    report = verify_draft(bare_draft, source_document=bare_draft)

    total_weight = sum(weight for _, _, _, weight in STRUCTURE_CHECKS)
    assert len(report.missing_structure) == len(STRUCTURE_CHECKS)
    assert report.confidence_score == round(max(0.0, 100.0 - total_weight), 1)


def test_strict_false_reports_unsupported_claims_without_forcing_approval():
    """other_official correspondence is allowed conventional boilerplate --
    ungrounded claims are still reported, but must not by themselves force
    human approval when strict=False."""
    draft = WELL_FORMED_DRAFT.replace("E-123-456", "E-999-999")
    report = verify_draft(draft, source_document="tamamen ilgisiz bir kaynak", strict=False)

    assert report.unsupported_claims
    assert report.requires_human_approval is False


def test_empty_draft_scores_zero_and_forces_approval():
    report = verify_draft("   ")

    assert report.confidence_score == 0.0
    assert report.requires_human_approval is True
    assert "boş" in report.evaluation_notes


def test_score_below_threshold_forces_approval_even_without_missing_structure():
    # Five fabricated document numbers: 5 * 12.0 = 60.0 penalty, at the
    # MAX_UNSUPPORTED_PENALTY cap, still below MIN_AUTOMATED_CONFIDENCE_SCORE.
    # Zero-padded so each matches DOCUMENT_NUMBER_PATTERN's \d{2,} minimum.
    numbers = " ".join(f"E-{i:02d}-999" for i in range(5))
    draft = WELL_FORMED_DRAFT + f"\n{numbers}"
    report = verify_draft(draft, source_document="Sayı: E-123-456 tarihli evrak.")

    assert report.confidence_score < MIN_AUTOMATED_CONFIDENCE_SCORE
    assert report.requires_human_approval is True
