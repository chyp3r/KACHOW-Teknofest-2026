"""Unit tests for the deterministic groundedness/structure verifier."""

from app.ai.verification.confidence_rules import RULES
from app.ai.verification.draft_verifier import (
    MIN_AUTOMATED_CONFIDENCE_SCORE,
    STRUCTURE_CHECKS,
    _STRUCTURE_RULE_IDS,
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


def test_the_drafts_own_number_line_echoing_the_incoming_documents_number_is_flagged():
    """The bug this guards against: the incoming document's own number is
    genuinely grounded (it's part of `classification`), so the general
    groundedness check alone has no reason to flag it -- being true doesn't
    make it allowed in the response's own Sayı: line. A response's own case
    number is assigned by the writing institution's registry, never copied
    from the document it replies to."""
    draft = WELL_FORMED_DRAFT.replace("Sayı: E-123-456", "Sayı: E-2026-998877")
    classification = {"fields": {"sayi": "E-2026-998877"}}

    report = verify_draft(
        draft, source_document="Diğer içerik.", classification=classification
    )

    assert len(report.incoming_number_leaks) == 1
    assert report.incoming_number_leaks[0].value == "E-2026-998877"
    assert report.requires_human_approval is True
    assert report.confidence_score < 100.0


def test_a_correctly_left_placeholder_sayi_line_is_not_a_leak():
    draft = WELL_FORMED_DRAFT.replace("Sayı: E-123-456", "Sayı: [Belge Sayısı]")
    classification = {"fields": {"sayi": "E-2026-998877"}}

    report = verify_draft(
        draft, source_document="Diğer içerik.", classification=classification
    )

    assert report.incoming_number_leaks == []


def test_a_reference_to_the_incoming_number_in_an_ilgi_line_is_not_a_leak():
    """The incoming number is legitimately quoted in an "İlgi:" line -- only
    the draft's own "Sayı:" line is checked."""
    draft = (
        "Konu: Yıllık İzin Talebi\n"
        "Sayı: [Belge Sayısı]\n"
        "Tarih: [Tarih]\n"
        "İlgi: E-2026-998877 sayılı yazınız.\n\n"
        "Sayın Makam,\n\nArz ederim.\n\nMehmet Öztürk\nGenel Müdür"
    )
    classification = {"fields": {"sayi": "E-2026-998877"}}

    report = verify_draft(
        draft, source_document="Diğer içerik.", classification=classification
    )

    assert report.incoming_number_leaks == []


def test_the_drafts_own_number_unrelated_to_the_incoming_one_is_not_a_leak():
    classification = {"fields": {"sayi": "E-2026-998877"}}

    report = verify_draft(
        WELL_FORMED_DRAFT, source_document="Diğer içerik.", classification=classification
    )

    # WELL_FORMED_DRAFT's own number (E-123-456) is unrelated to the
    # incoming one -- still an ordinary unsupported claim (nothing grounds
    # it), but not the specific incoming-number-leak rule.
    assert report.incoming_number_leaks == []


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
    the exact sum of every structure rule's own penalty (confidence_rules.
    RULES, via _STRUCTURE_RULE_IDS), not a partial or capped amount."""
    bare_draft = "Bu metinde hiçbir resmi unsur yok."
    report = verify_draft(bare_draft, source_document=bare_draft)

    total_weight = sum(
        RULES[_STRUCTURE_RULE_IDS[key]].penalty for key, _, _ in STRUCTURE_CHECKS
    )
    assert len(report.missing_structure) == len(STRUCTURE_CHECKS)
    assert report.confidence_score == round(max(0.0, 100.0 - total_weight), 1)
    assert len(report.applied_rules) == len(STRUCTURE_CHECKS)


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


# --- Type-aware canonical matching -------------------------------------------
#
# The measured baseline (evaluation/reports/all-baseline.md) showed every false
# positive this gate produced was a format mismatch rather than a fabrication:
# a date, citation or amount written differently from the source but meaning
# exactly the same thing. Each one cost a correct draft a HITL interruption, so
# these tests pin the canonical rung that closes the gap -- and, just as
# importantly, pin that it did not become fuzzy matching on values that need
# equality.


def test_date_written_in_words_is_grounded_by_a_numeric_source_date():
    draft = WELL_FORMED_DRAFT.replace("30.07.2026", "30 Temmuz 2026")

    report = verify_draft(draft, source_document="Sayı: E-123-456 Tarih: 30.07.2026")

    assert report.unsupported_claims == []
    assert not report.requires_human_approval


def test_numeric_date_is_grounded_by_a_source_date_written_in_words():
    """The relation has to hold in both directions, not just draft -> source."""
    report = verify_draft(
        WELL_FORMED_DRAFT,
        source_document="Sayı: E-123-456 Tarih: 30 Temmuz 2026",
    )

    assert report.unsupported_claims == []


def test_a_different_date_is_still_flagged_after_canonicalisation():
    """The safety property: canonicalisation must not launder a wrong date."""
    draft = WELL_FORMED_DRAFT.replace("30.07.2026", "31 Temmuz 2026")

    report = verify_draft(draft, source_document="Sayı: E-123-456 Tarih: 30.07.2026")

    assert [claim.kind for claim in report.unsupported_claims] == ["tarih"]
    assert report.unsupported_claims[0].canonical == "2026-07-31"


def test_abbreviated_article_citation_is_grounded_by_the_long_form():
    draft = WELL_FORMED_DRAFT.replace("Arz ederim.", "m. 11 uyarınca arz ederim.")

    report = verify_draft(
        draft,
        source_document="Sayı: E-123-456 Tarih: 30.07.2026",
        context="4982 sayılı Kanun Madde 11 - Onbeş iş günü içinde erişim sağlanır.",
    )

    assert report.unsupported_claims == []


def test_amount_without_decimals_is_grounded_by_the_same_amount_with_them():
    draft = WELL_FORMED_DRAFT.replace("Arz ederim.", "125.000 TL tutarını arz ederim.")

    report = verify_draft(
        draft,
        source_document="Sayı: E-123-456 Tarih: 30.07.2026 Tutar: 125.000,00 TL",
    )

    assert report.unsupported_claims == []


def test_a_different_amount_is_still_flagged():
    draft = WELL_FORMED_DRAFT.replace("Arz ederim.", "125.500 TL tutarını arz ederim.")

    report = verify_draft(
        draft,
        source_document="Sayı: E-123-456 Tarih: 30.07.2026 Tutar: 125.000,00 TL",
    )

    assert [claim.kind for claim in report.unsupported_claims] == ["tutar"]


def test_an_all_caps_turkish_letterhead_grounds_the_same_institution_in_title_case():
    """Regression: `_fold` ran NFKD without translating Turkish letters first.
    'ı' (U+0131, dotless i) has no NFKD decomposition, so ascii/ignore silently
    deleted it, while plain ASCII 'I' in an all-caps source survived and folded
    to 'i' -- 'Kadıköy Kaymakamlığı' (draft) and 'KADIKÖY KAYMAKAMLIĞI' (an
    all-caps letterhead -- the standard Turkish convention, and also what OCR of
    a scanned header produces) folded to two different strings. A draft that
    copied the institution name straight off the source's own letterhead was
    flagged as fabricating it -- twice, since the source's own occurrence didn't
    match itself either.

    The institution phrase is placed after a lowercase word, same reasoning as
    `test_institution_paraphrase_escape_hatch_via_token_overlap` above:
    INSTITUTION_PATTERN's leading capitalized-word group is greedy, so a
    preceding capitalized word (e.g. "Sayın") would be swallowed into the
    match and the folded claim would carry an extra token the source doesn't
    have -- a separate, pre-existing quirk this test must not conflate with
    the Turkish-folding bug it is actually checking.
    """
    draft = (
        "Konu: Yıllık İzin Talebi\n"
        "Sayı: E-123-456\n"
        "Tarih: 30.07.2026\n\n"
        "Sayın Makam, konu hakkında yerel şubemiz Kadıköy Kaymakamlığı'na bilgi vermiştir.\n\n"
        "Arz ederim.\n\n"
        "Mehmet Öztürk\nGenel Müdür"
    )
    report = verify_draft(
        draft,
        source_document="T.C.\nKADIKÖY KAYMAKAMLIĞI\nSayı: E-123-456 Tarih: 30.07.2026",
    )

    assert not any(claim.kind == "kurum" for claim in report.unsupported_claims)


def test_document_number_separator_style_does_not_matter():
    draft = WELL_FORMED_DRAFT.replace("E-123-456", "E/123/456")

    report = verify_draft(draft, source_document="Sayı: E-123-456 Tarih: 30.07.2026")

    assert report.unsupported_claims == []


def test_an_unsupported_claim_reports_the_form_that_was_searched_for():
    """Evidence, not just a verdict -- the report has to be actionable."""
    draft = WELL_FORMED_DRAFT.replace("E-123-456", "E-999-999")

    report = verify_draft(draft, source_document="Sayı: E-123-456 Tarih: 30.07.2026")

    claim = next(item for item in report.unsupported_claims if item.kind == "sayı")
    assert claim.canonical == "e999999"
    assert 0.0 <= claim.best_overlap <= 1.0


def test_a_reference_number_is_not_read_as_a_legislation_citation():
    """"E-...-118 sayılı yazınız" must not yield a phantom "118 sayılı" citation.

    Before the lookbehind guard this produced a fabricated-reference finding on
    a grounded draft whenever no other "N sayılı" citation happened to be in
    context for the token-overlap fallback to latch onto.
    """
    draft = WELL_FORMED_DRAFT.replace(
        "Arz ederim.", "İlgi: E-22222222-903-118 sayılı yazınız. Arz ederim."
    )

    report = verify_draft(
        draft,
        source_document="Sayı: E-123-456 Tarih: 30.07.2026 İlgi: E-22222222-903-118",
    )

    assert [claim.value for claim in report.unsupported_claims] == []


def test_a_genuine_law_citation_is_still_extracted():
    """The lookbehind must not blind the pattern to real citations."""
    draft = WELL_FORMED_DRAFT.replace("Arz ederim.", "9999 sayılı Kanun uyarınca arz ederim.")

    report = verify_draft(
        draft,
        source_document="Sayı: E-123-456 Tarih: 30.07.2026",
        context="4982 sayılı Kanun Madde 11",
    )

    assert [claim.kind for claim in report.unsupported_claims] == ["mevzuat"]
    assert report.unsupported_claims[0].canonical == "kanun:9999"


# --- Few-shot style-example leak detection -----------------------------------
#
# A style example is a real letter, not a synthetic one -- it carries genuine
# institution names, dates and case numbers. writer.md instructs the model not
# to copy them, but a prompt instruction is not a guarantee, so verify_draft
# closes the loop deterministically: any unsupported claim that also appears
# in a style example is split into example_leaks and always forces approval.


def _draft_mentioning(institution: str) -> str:
    return (
        "Konu: Yıllık İzin Talebi\n"
        "Sayı: E-123-456\n"
        "Tarih: 30.07.2026\n\n"
        f"Sayın Makam, konu hakkında yerel şubemiz {institution}'na bilgi vermiştir.\n\n"
        "Arz ederim.\n\n"
        "Mehmet Öztürk\nGenel Müdür"
    )


def test_a_value_only_present_in_a_style_example_is_flagged_as_a_leak():
    draft = _draft_mentioning("Bursa Kaymakamlığı")
    report = verify_draft(
        draft,
        source_document="Sayı: E-123-456, Tarih: 30.07.2026 tarihli evrak.",
        style_examples=["Bu örnek yazı Bursa Kaymakamlığı tarafından hazırlanmıştır."],
    )

    assert [claim.value for claim in report.example_leaks] == ["Bursa Kaymakamlığı"]
    assert report.example_leaks[0].kind == "ornek_sizintisi"
    # Split out of unsupported_claims, not duplicated into it -- otherwise the
    # same leak would also feed a revision repair item.
    assert not any(claim.kind == "kurum" for claim in report.unsupported_claims)
    assert report.requires_human_approval is True


def test_a_value_also_grounded_in_the_source_is_not_a_leak():
    draft = _draft_mentioning("Bursa Kaymakamlığı")
    report = verify_draft(
        draft,
        source_document="Bursa Kaymakamlığı tarafından gönderilen yazı üzerine.",
        style_examples=["Bu örnek yazı Bursa Kaymakamlığı tarafından hazırlanmıştır."],
    )

    assert report.example_leaks == []


def test_an_example_leak_forces_approval_even_when_strict_is_false():
    """other_official's leniency covers conventional boilerplate, not a real
    fact copied from a retrieved example -- the two are different problems."""
    draft = _draft_mentioning("Bursa Kaymakamlığı")
    report = verify_draft(
        draft,
        source_document="tamamen ilgisiz bir kaynak",
        style_examples=["Bu örnek yazı Bursa Kaymakamlığı tarafından hazırlanmıştır."],
        strict=False,
    )

    assert report.example_leaks
    assert report.requires_human_approval is True


def test_no_style_examples_leaves_unsupported_claims_unaffected():
    """Regression guard: omitting style_examples must reproduce pre-feature
    behaviour exactly, not just "no leaks found"."""
    draft = WELL_FORMED_DRAFT.replace("E-123-456", "E-999-999")
    report = verify_draft(draft, source_document="Sayı: E-123-456 tarihli evrak.")

    assert report.example_leaks == []
    assert any(claim.kind == "sayı" for claim in report.unsupported_claims)


# ===========================================================================
# instruction_only_claims -- a claim traced only to the user's own revision
# instruction, not to the source document or mevzuat context.
# ===========================================================================
def test_a_value_only_present_in_the_instruction_is_split_out_not_penalized():
    draft = WELL_FORMED_DRAFT.replace("E-123-456", "E-999-999")
    report = verify_draft(
        draft,
        source_document="Sayı: E-123-456, Tarih: 30.07.2026 tarihli evrak.",
        instructions="Sayıyı E-999-999 olarak güncelle.",
    )

    assert [claim.value for claim in report.instruction_only_claims] == ["E-999-999"]
    # Split out of unsupported_claims -- the user's own word is trusted by
    # construction, exactly as it was before this field existed.
    assert not any(claim.kind == "sayı" for claim in report.unsupported_claims)
    assert report.confidence_score == 100.0
    assert report.requires_human_approval is False


def test_a_value_in_both_the_instruction_and_an_example_is_instruction_only_not_a_leak():
    """User supremacy: a value the user explicitly typed must never be
    mislabeled as a leaked style example just because it also happens to
    appear in one -- see draft_verifier.verify_draft's docstring."""
    draft = _draft_mentioning("Bursa Kaymakamlığı")
    report = verify_draft(
        draft,
        source_document="Sayı: E-123-456, Tarih: 30.07.2026 tarihli evrak.",
        instructions="Yerel şube olarak Bursa Kaymakamlığı'nı yaz.",
        style_examples=["Bu örnek yazı Bursa Kaymakamlığı tarafından hazırlanmıştır."],
    )

    assert report.example_leaks == []
    assert [claim.value for claim in report.instruction_only_claims] == ["Bursa Kaymakamlığı"]
    assert report.requires_human_approval is False


def test_a_value_grounded_in_the_source_is_not_also_instruction_only():
    report = verify_draft(
        WELL_FORMED_DRAFT,
        source_document="Sayı: E-123-456, Tarih: 30.07.2026 tarihli evrak.",
        instructions="Sayıyı E-123-456 olarak bırak.",
    )

    assert report.instruction_only_claims == []
