"""Unit tests for the decomposition and re-retrieval signal added on top of
the pre-existing deterministic instruction parsing (see test_revise_flow.py
for the parser/locator/merge tests that predate this module)."""

from app.ai.revision.instruction import (
    decompose_instruction,
    locate_target,
    needs_reretrieval,
    parse_revision_instruction,
)

DRAFT = (
    "Konu: Personel İzin Talebi\n\n"
    "Sayın Makam,\n\n"
    "İlgi yazı kapsamında personelimizin izin talebi tarafımıza iletilmiştir.\n\n"
    "Arz ederim.\n\n"
    "Ali Veli\nGenel Müdür"
)


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
