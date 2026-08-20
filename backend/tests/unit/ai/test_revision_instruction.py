"""Unit tests for the decomposition and re-retrieval signal added on top of
the pre-existing deterministic instruction parsing (see test_revise_flow.py
for the parser/locator/merge tests that predate this module)."""

from app.ai.revision.instruction import (
    TargetSpan,
    decompose_instruction,
    locate_target,
    needs_reretrieval,
    parse_revision_instruction,
    resolve_merge_target,
    spans_overlap,
)

DRAFT = (
    "Konu: Personel İzin Talebi\n\n"
    "Sayın Makam,\n\n"
    "İlgi yazı kapsamında personelimizin izin talebi tarafımıza iletilmiştir.\n\n"
    "Arz ederim.\n\n"
    "Ali Veli\nGenel Müdür"
)

#: A generated draft's real header shape (Konu/Sayı/Tarih on consecutive
#: lines, no blank line between them -- see writer.md's fixed structure),
#: unlike DRAFT above which only carries a bare "Konu:" line. Used
#: specifically to reproduce the "sayıyı siliyor" bug report: a target
#: span that includes "Sayı:" being handed to the reviser for an unrelated
#: body edit.
FULL_HEADER_DRAFT = (
    "Konu: Yıllık İzin Talebi\n"
    "Sayı: E-2026-123\n"
    "Tarih: 18.08.2026\n\n"
    "Sayın Makam,\n\n"
    "İlgi yazı kapsamında personelimizin izin talebi tarafımıza iletilmiştir.\n\n"
    "Arz ederim.\n\n"
    "Ali Veli\nGenel Müdür"
)


# ===========================================================================
# The "sayıyı siliyor" bug: a header block spanning Konu/Sayı/Tarih together
# must never be handed to the reviser as the target for "1. paragraf"/
# "giriş" -- see instruction.py's _is_header_paragraph docstring.
# ===========================================================================
def test_the_full_header_block_is_never_the_first_paragraph_target():
    instruction = parse_revision_instruction("İlk paragrafı daha resmi yap.")
    target = locate_target(FULL_HEADER_DRAFT, instruction)

    assert target is not None
    assert "Sayı:" not in target.text
    assert "Konu:" not in target.text
    assert target.text == "Sayın Makam,"


def test_a_numbered_ordinal_also_skips_the_full_header_block():
    instruction = parse_revision_instruction("1. paragrafı sil.")
    target = locate_target(FULL_HEADER_DRAFT, instruction)

    assert target is not None
    assert "Sayı:" not in target.text


def test_the_konu_section_hint_still_finds_the_header_block_directly():
    """konu's own hint must keep working unchanged -- it explicitly means
    to find the header's Konu line, unlike ordinal/giriş which must skip
    past it."""
    instruction = parse_revision_instruction("Konu satırını değiştir.")
    target = locate_target(FULL_HEADER_DRAFT, instruction)

    assert target is not None
    assert "Sayı:" in target.text
    assert target.text.startswith("Konu:")


def test_konuyu_degistir_also_resolves_to_the_konu_hint():
    """The bare accusative form ("konuyu") must resolve the same way the
    longer "konu satırını" phrasing does -- both name the letter's own
    Konu field."""
    instruction = parse_revision_instruction("Konuyu değiştir.")
    assert instruction.section_hint == "konu"


# ===========================================================================
# C20: a bare "konu" must not misfire on the generic Turkish noun ("bu
# konuda" = "on this topic") -- only the field-naming forms should resolve
# to the konu section hint at all.
# ===========================================================================
def test_a_generic_topic_reference_does_not_resolve_to_the_konu_section_hint():
    instruction = parse_revision_instruction("Bu konuda daha resmi bir dil kullan.")
    assert instruction.section_hint != "konu"
    assert instruction.scope == "whole"


def test_a_generic_topic_reference_targets_the_whole_draft_not_just_konu():
    instruction = parse_revision_instruction("Bu konuda daha resmi bir dil kullan.")
    target = locate_target(FULL_HEADER_DRAFT, instruction)
    assert target is None  # whole-draft scope, not narrowed to the header


# ===========================================================================
# C19: "N paragraf ekle" is a count of paragraphs to *add*, not the ordinal
# index of an existing one to edit -- must not resolve the same way "N.
# paragrafı düzelt" (an ordinal edit target) does.
# ===========================================================================
def test_a_paragraph_addition_request_is_not_read_as_an_ordinal_target():
    instruction = parse_revision_instruction("Metne 2 paragraf daha ekle.")
    assert instruction.ordinal is None
    assert instruction.scope == "whole"


def test_an_ordinal_edit_request_is_still_read_as_an_ordinal_target():
    instruction = parse_revision_instruction("2. paragrafı kısalt.")
    assert instruction.ordinal == 2
    assert instruction.scope == "paragraph"


# ===========================================================================
# decompose_instruction
# ===========================================================================
def test_a_compound_instruction_splits_into_two_directives():
    directives = decompose_instruction("Konuyu değiştir ve son paragrafı kısalt.")
    assert len(directives) == 2
    assert directives[0].section_hint == "konu"
    assert directives[1].scope == "paragraph"
    assert directives[1].ordinal == -1
    assert directives[1].operation == "shorten"


def test_a_single_clause_instruction_yields_one_directive_carrying_the_full_text():
    directives = decompose_instruction("Kısalt lütfen.")
    assert len(directives) == 1
    assert directives[0].raw == "Kısalt lütfen."


def test_an_unsplittable_instruction_falls_back_to_whole_scope():
    directives = decompose_instruction("Bunu daha iyi yap.")
    assert len(directives) == 1
    assert directives[0].scope == "whole"
    assert directives[0].raw == "Bunu daha iyi yap."


def test_an_unlocatable_clause_alongside_a_located_one_falls_back_to_whole_scope():
    """The bug this guards against: "muhatap Ankara Valiliği" names neither a
    section nor an operation, so it cannot ride along inside the "Konuyu
    değiştir" directive's own located span (a directive's prompt is confined
    to its own span) -- it used to be silently dropped. The whole compound
    instruction must fall back to one whole-draft rewrite instead, carrying
    every clause's own text, rather than re-discovering just the "konu"
    location from one clause and misapplying the whole ask to it."""
    directives = decompose_instruction("Konuyu değiştir ve muhatap Ankara Valiliği olsun.")

    assert len(directives) == 1
    assert directives[0].scope == "whole"
    assert directives[0].raw == "Konuyu değiştir ve muhatap Ankara Valiliği olsun."


def test_a_fully_locatable_compound_instruction_still_decomposes_normally():
    """Regression guard: the new fallback must not fire when every clause
    *does* locate -- that is exactly the precise-splice case this module
    exists for."""
    directives = decompose_instruction("Konuyu değiştir ve son paragrafı kısalt.")

    assert len(directives) == 2


def test_each_directive_locates_independently_in_the_original_draft():
    directives = decompose_instruction("Konuyu değiştir ve son paragrafı kısalt.")
    konu_target = locate_target(DRAFT, directives[0])
    last_target = locate_target(DRAFT, directives[1])

    assert konu_target is not None and konu_target.text.startswith("Konu:")
    assert last_target is not None and "Genel Müdür" in last_target.text
    # Spans computed against the same original draft do not overlap and the
    # later one is not shifted by the earlier one -- both are still valid
    # offsets into DRAFT, not into a partially-rewritten copy.
    assert konu_target.end <= last_target.start


# ===========================================================================
# parse_revision_instruction carries the new fields
# ===========================================================================
def test_parse_revision_instruction_still_returns_the_original_fields():
    instruction = parse_revision_instruction("3. paragrafı kısalt.")
    assert instruction.scope == "paragraph"
    assert instruction.ordinal == 3
    assert instruction.operation == "shorten"
    assert len(instruction.directives) >= 1


# ===========================================================================
# needs_reretrieval
# ===========================================================================
def test_a_legislation_reference_triggers_reretrieval():
    instruction = parse_revision_instruction("4982 sayılı Kanuna atıf ekle.")
    assert instruction.introduces_normative_content is True
    assert needs_reretrieval(instruction) is True


def test_an_article_reference_triggers_reretrieval():
    instruction = parse_revision_instruction("Madde 12 uyarınca gerekçe ekle.")
    assert needs_reretrieval(instruction) is True


def test_a_pure_tone_request_does_not_trigger_reretrieval():
    instruction = parse_revision_instruction("Daha resmi yap.")
    assert instruction.introduces_normative_content is False
    assert needs_reretrieval(instruction) is False


def test_a_shorten_request_does_not_trigger_reretrieval():
    instruction = parse_revision_instruction("Kısalt lütfen.")
    assert needs_reretrieval(instruction) is False


# ===========================================================================
# C22: a directive's rewrite that ignores its own narrow scope and
# regenerates (close to) the whole draft must not be spliced in at the
# original span -- that would double the content instead of replacing it.
# ===========================================================================
def _target(text: str) -> TargetSpan:
    return TargetSpan(start=0, end=len(text), text=text)


def test_an_ordinary_rewrite_keeps_its_own_target():
    target = _target("Kısa bir paragraf.")
    rewritten = "Biraz daha uzun ama makul bir paragraf oldu."
    source = f"Konu: X\n\n{target.text}\n\nArz ederim.\n\nAli Veli"

    assert resolve_merge_target(target, rewritten, source) is target


def test_a_whole_draft_sized_rewrite_of_a_narrow_target_is_rejected():
    target = _target("Kısa bir paragraf.")
    source = (
        "Konu: X\nSayı: E-1-1\nTarih: 18.08.2026\n\n"
        f"Sayın Makam,\n\n{target.text}\n\nArz ederim.\n\nAli Veli\nGenel Müdür"
    )
    # The model ignored the scope rule and regenerated something as long as
    # (and shaped like) the whole draft, not just the targeted paragraph.
    rewritten = source.replace(target.text, "Tamamen yeniden yazılmış içerik burada.")

    assert resolve_merge_target(target, rewritten, source) is None


def test_a_none_target_is_never_flagged_as_an_overrun():
    assert resolve_merge_target(None, "herhangi bir metin", "kaynak taslak") is None


def test_an_empty_target_span_is_never_flagged_as_an_overrun():
    target = _target("")
    assert resolve_merge_target(target, "yeni içerik", "kaynak taslak") is target


# ===========================================================================
# C5: overlapping directive spans must be detected before the right-to-left
# multi-directive merge -- splicing two overlapping spans corrupts offsets.
# ===========================================================================
def test_disjoint_spans_do_not_overlap():
    assert spans_overlap([TargetSpan(0, 5, "x"), TargetSpan(10, 15, "y")]) is False


def test_adjacent_touching_spans_do_not_overlap():
    assert spans_overlap([TargetSpan(0, 5, "x"), TargetSpan(5, 10, "y")]) is False


def test_intersecting_spans_overlap():
    assert spans_overlap([TargetSpan(0, 10, "x"), TargetSpan(5, 15, "y")]) is True


def test_a_none_target_is_ignored_when_checking_for_overlap():
    assert spans_overlap([TargetSpan(0, 5, "x"), None]) is False
