"""Unit tests for the revise flow's deterministic pieces and its one LLM call.

parse_revision_instruction/locate_target/_merge are pure and tested directly;
run_revise is exercised end-to-end with FakeLLMClient (a real BaseLLMClient
subclass, see conftest.py) so the merge's structural guarantee -- the
untouched head and tail are byte-identical to the original, by construction,
not by post-hoc comparison -- is proven on the actual output, not asserted
about the mechanism in the abstract.
"""

import pytest

from app.ai.session.focus import DraftVersion
from app.ai.workflows.revise import (
    _merge,
    locate_target,
    parse_revision_instruction,
    run_revise,
)
from app.core.enums.step_status import StepStatus

DRAFT = (
    "Konu: Personel İzin Talebi\n\n"
    "Sayın Makam,\n\n"
    "İlgi yazı kapsamında personelimizin izin talebi tarafımıza iletilmiştir.\n\n"
    "Arz ederim.\n\n"
    "Ali Veli\nGenel Müdür"
)


# ===========================================================================
# parse_revision_instruction
# ===========================================================================
def test_an_ordinal_paragraph_reference_is_recognized():
    instruction = parse_revision_instruction("3. paragrafı kısalt.")
    assert instruction.scope == "paragraph"
    assert instruction.ordinal == 3
    assert instruction.operation == "shorten"


def test_last_paragraph_is_recognized_by_word():
    instruction = parse_revision_instruction("Son paragrafı daha resmi yap.")
    assert instruction.scope == "paragraph"
    assert instruction.ordinal == -1
    assert instruction.operation == "tone_formal"


def test_a_named_section_is_recognized():
    instruction = parse_revision_instruction("Kapanış kısmını değiştir.")
    assert instruction.scope == "section"
    assert instruction.section_hint == "kapanis"


def test_an_unspecific_instruction_targets_the_whole_draft():
    instruction = parse_revision_instruction("Bunu daha iyi yap.")
    assert instruction.scope == "whole"
    assert instruction.section_hint is None
    assert instruction.ordinal is None


def test_raw_text_is_preserved_verbatim():
    instruction = parse_revision_instruction("Kısalt lütfen.")
    assert instruction.raw == "Kısalt lütfen."


# ===========================================================================
# locate_target
# ===========================================================================
def test_locate_target_finds_an_ordinal_paragraph():
    """Ordinal counting skips the letter's own metadata header ("Konu: ...",
    a single blank-line-separated block) -- see instruction.py's
    _is_header_paragraph docstring for the bug this guards against (a bare
    "1. paragraf"/"ilk paragraf"/"giriş" used to land on that header block
    instead, exposing "Sayı:" to an unrelated body edit). So "2. paragraf"
    here is the *second* real content block after the header, not the
    header-adjacent salutation."""
    instruction = parse_revision_instruction("2. paragrafı değiştir.")
    target = locate_target(DRAFT, instruction)

    assert target is not None
    assert target.text == "İlgi yazı kapsamında personelimizin izin talebi tarafımıza iletilmiştir."


def test_locate_target_skips_the_metadata_header_for_the_first_paragraph():
    """The direct regression test for the bug: "1. paragrafı"/"ilk
    paragraf" must never resolve to the "Konu: ..." header block."""
    instruction = parse_revision_instruction("1. paragrafı değiştir.")
    target = locate_target(DRAFT, instruction)

    assert target is not None
    assert target.text == "Sayın Makam,"
    assert "Konu" not in target.text


def test_locate_target_finds_the_last_paragraph_by_negative_ordinal():
    instruction = parse_revision_instruction("Son paragrafı değiştir.")
    target = locate_target(DRAFT, instruction)

    assert target is not None
    assert "Genel Müdür" in target.text


def test_locate_target_finds_the_closing_section_structurally():
    instruction = parse_revision_instruction("Kapanışı değiştir.")
    target = locate_target(DRAFT, instruction)

    assert target is not None
    assert "Arz ederim" in target.text


def test_locate_target_finds_the_subject_line():
    instruction = parse_revision_instruction("Konuyu değiştir.")
    target = locate_target(DRAFT, instruction)

    assert target is not None
    assert target.text.startswith("Konu:")


def test_locate_target_skips_the_metadata_header_for_giris():
    """Same regression as the "1. paragraf" case above, via the "giriş"
    section-hint path instead of an ordinal -- both must skip the header."""
    instruction = parse_revision_instruction("Girişi daha resmi yap.")
    target = locate_target(DRAFT, instruction)

    assert target is not None
    assert target.text == "Sayın Makam,"
    assert "Konu" not in target.text


def test_locate_target_returns_none_for_whole_scope():
    instruction = parse_revision_instruction("Bunu daha iyi yap.")
    assert locate_target(DRAFT, instruction) is None


def test_locate_target_returns_none_for_an_out_of_range_ordinal():
    instruction = parse_revision_instruction("99. paragrafı değiştir.")
    assert locate_target(DRAFT, instruction) is None


# ===========================================================================
# _merge -- the structural "no unintended change" guarantee
# ===========================================================================
def test_merge_splices_the_rewrite_into_the_target_span():
    instruction = parse_revision_instruction("2. paragrafı değiştir.")
    target = locate_target(DRAFT, instruction)

    merged = _merge(DRAFT, target, "Sayın Vali Bey,")

    assert "Sayın Vali Bey," in merged
    # Everything outside the target span is byte-identical to the original,
    # by construction (see module docstring) -- not merely unchanged, but
    # structurally impossible to have changed.
    assert merged[: target.start] == DRAFT[: target.start]
    assert merged[target.start + len("Sayın Vali Bey,") :] == DRAFT[target.end :]


def test_merge_with_no_target_replaces_the_whole_draft():
    assert _merge(DRAFT, None, "  Yeni tam taslak.  ") == "Yeni tam taslak."


# ===========================================================================
# run_revise -- end to end with a real (fake) LLM client
# ===========================================================================
_ACTIVE_DRAFT = DraftVersion(
    version=1,
    text=DRAFT,
    correspondence_type="response_letter",
    confidence_score=85.0,
    created_from="draft",
    classification={"summary": "Personel izin talebine ilişkin yazı."},
    context="[MEVZUAT] İlgili Yönetmelik Madde 5: ...",
    source_document="Sayı: 2026/1, personel izin talebi.",
)


@pytest.mark.asyncio
async def test_run_revise_targets_only_the_requested_paragraph(fake_llm):
    fake_llm.stream_chunks = ["Personel izin talebi ivedilikle değerlendirilmelidir."]

    result = await run_revise(
        active_draft=_ACTIVE_DRAFT,
        instructions="2. paragrafı 'Personel izin talebi ivedilikle değerlendirilmelidir.' olarak değiştir.",
        correspondence_type="response_letter",
        llm_client=fake_llm,
        fast_llm_client=None,
        reasoning_level="fast",
    )

    assert "Personel izin talebi ivedilikle değerlendirilmelidir." in result["draft"]
    assert "Sayın Makam," in result["draft"]  # untouched paragraph survives
    # ...and the metadata header, which "2. paragraf" now correctly skips
    # past (see instruction.py's _is_header_paragraph), is untouched too.
    assert "Konu: Personel İzin Talebi" in result["draft"]
    assert result["classification"] == _ACTIVE_DRAFT.classification
    assert result["context"] == _ACTIVE_DRAFT.context
    assert result["source_document"] == _ACTIVE_DRAFT.source_document


@pytest.mark.asyncio
async def test_run_revise_surfaces_applied_rules_and_attempts(fake_llm):
    """C29: these two used to fall out of run_revise's own result dict --
    revise_graph.verify_node computes and returns both, but this façade
    never surfaced them, so every revised draft persisted with an empty
    applied_rules and no attempt count regardless of what the sub-graph
    actually did."""
    fake_llm.stream_chunks = ["Personel izin talebi ivedilikle değerlendirilmelidir."]

    result = await run_revise(
        active_draft=_ACTIVE_DRAFT,
        instructions="2. paragrafı 'Personel izin talebi ivedilikle değerlendirilmelidir.' olarak değiştir.",
        correspondence_type="response_letter",
        llm_client=fake_llm,
        fast_llm_client=None,
        reasoning_level="fast",
    )

    assert "applied_rules" in result
    assert isinstance(result["applied_rules"], list)
    assert result["attempts"] >= 1


@pytest.mark.asyncio
async def test_run_revise_falls_back_to_the_draft_s_own_type_when_none_is_given(fake_llm):
    fake_llm.stream_chunks = ["Yeni tam taslak metni."]

    result = await run_revise(
        active_draft=_ACTIVE_DRAFT,
        instructions="Tamamını sadeleştir.",
        correspondence_type="",
        llm_client=fake_llm,
        fast_llm_client=None,
        reasoning_level="fast",
    )

    assert result["correspondence_type"] == "response_letter"


@pytest.mark.asyncio
async def test_an_empty_rewrite_fails_without_discarding_the_prior_draft(fake_llm):
    fake_llm.stream_chunks = ["   "]

    result = await run_revise(
        active_draft=_ACTIVE_DRAFT,
        instructions="Kısalt.",
        correspondence_type="response_letter",
        llm_client=fake_llm,
        fast_llm_client=None,
        reasoning_level="fast",
    )

    assert result["status"] == StepStatus.FAILED
    assert result["draft"] == _ACTIVE_DRAFT.text
