"""Unit tests for the deterministic + LLM instruction-vs-mevzuat/source
conflict audit. Every scenario asserts the invariant from the module
docstring: findings never suppress or revert the applied edit -- they only
attach a warning."""

import pytest

from app.ai.agents.conflict_auditor import ConflictAuditorAgent
from app.ai.revision.conflict import (
    ConflictAssessment,
    LlmConflictFinding,
    assess_conflicts_llm,
    detect_conflicts_deterministic,
    merge_conflicts,
)
from app.ai.revision.instruction import parse_revision_instruction
from app.ai.verification.draft_verifier import verify_draft

#: A real checksum-valid TCKN (see test_pii.py), not a live person's.
VALID_TCKN = "12345678950"

WELL_FORMED_DRAFT = (
    "Konu: Yıllık İzin Talebi\n"
    "Sayı: E-123-456\n"
    "Tarih: 30.07.2026\n\n"
    "Sayın Makam,\n\n"
    "Arz ederim.\n\n"
    "Mehmet Öztürk\nGenel Müdür"
)


def _report_for(draft: str, *, source_document: str = "", context: str = "", instructions: str = ""):
    return verify_draft(
        draft, source_document=source_document, context=context, instructions=instructions
    )


# ===========================================================================
# detect_conflicts_deterministic
# ===========================================================================
def test_a_citation_absent_from_context_is_flagged_as_unfounded():
    instruction = parse_revision_instruction("4982 sayılı Kanuna atıf ekle.")
    report = _report_for(WELL_FORMED_DRAFT)

    findings = detect_conflicts_deterministic(
        instruction=instruction, context="İlgisiz bir mevzuat metni.",
        source_document="", report=report,
    )

    assert any(f.kind == "mevzuat_dayanaksiz" for f in findings)


def test_a_citation_present_in_context_is_not_flagged():
    instruction = parse_revision_instruction("4982 sayılı Kanuna atıf ekle.")
    report = _report_for(WELL_FORMED_DRAFT)

    findings = detect_conflicts_deterministic(
        instruction=instruction, context="4982 sayılı Kanun uyarınca...",
        source_document="", report=report,
    )

    assert not any(f.kind == "mevzuat_dayanaksiz" for f in findings)


def test_a_date_contradicting_the_source_is_flagged_as_critical():
    instruction = parse_revision_instruction("Tarihi 01.01.2027 olarak değiştir.")
    report = _report_for(WELL_FORMED_DRAFT)

    findings = detect_conflicts_deterministic(
        instruction=instruction, context="",
        source_document="Bu evrak 30.07.2026 tarihlidir.", report=report,
    )

    conflict = next(f for f in findings if f.kind == "kaynak_celiskisi")
    assert conflict.severity == "critical"


def test_a_date_matching_the_source_is_not_a_conflict():
    instruction = parse_revision_instruction("Tarihi 30.07.2026 olarak bırak.")
    report = _report_for(WELL_FORMED_DRAFT)

    findings = detect_conflicts_deterministic(
        instruction=instruction, context="",
        source_document="Bu evrak 30.07.2026 tarihlidir.", report=report,
    )

    assert not any(f.kind == "kaynak_celiskisi" for f in findings)


def test_removing_a_mandatory_element_that_is_actually_missing_is_flagged():
    instruction = parse_revision_instruction("Kapanışı kaldır.")
    draft_without_closing = WELL_FORMED_DRAFT.replace("Arz ederim.\n\n", "")
    report = _report_for(draft_without_closing)

    findings = detect_conflicts_deterministic(
        instruction=instruction, context="", source_document="", report=report,
    )

    assert any(f.kind == "yapisal_ihlal" for f in findings)


def test_removal_phrase_without_an_actual_loss_is_not_flagged():
    """The draft still has a closing -- the instruction's wording alone
    (without evidence in the actual revised draft) must not be enough."""
    instruction = parse_revision_instruction("Kapanışı kaldır.")
    report = _report_for(WELL_FORMED_DRAFT)  # closing is present

    findings = detect_conflicts_deterministic(
        instruction=instruction, context="", source_document="", report=report,
    )

    assert not any(f.kind == "yapisal_ihlal" for f in findings)


def test_personal_data_in_the_instruction_is_flagged():
    instruction = parse_revision_instruction(f"T.C. Kimlik No: {VALID_TCKN} olarak ekle.")
    report = _report_for(WELL_FORMED_DRAFT)

    findings = detect_conflicts_deterministic(
        instruction=instruction, context="", source_document="", report=report,
    )

    conflict = next(f for f in findings if f.kind == "kisisel_veri")
    assert VALID_TCKN not in conflict.evidence


def test_an_instruction_only_institution_claim_is_a_weak_conflict():
    instruction = parse_revision_instruction("Muhatabı Ankara Valiliği olarak yaz.")
    draft = WELL_FORMED_DRAFT.replace(
        "Sayın Makam,\n\n", "Sayın Makam,\n\nAnkara Valiliği'ne bilgi verilmiştir.\n\n"
    )
    report = _report_for(draft, instructions=instruction.raw)

    findings = detect_conflicts_deterministic(
        instruction=instruction, context="", source_document="", report=report,
    )

    weak = [f for f in findings if f.kind == "mevzuat_celiskisi"]
    assert weak and weak[0].severity == "minor"


def test_a_tone_only_instruction_produces_no_findings():
    instruction = parse_revision_instruction("Daha resmi bir üslup kullan.")
    report = _report_for(WELL_FORMED_DRAFT)

    findings = detect_conflicts_deterministic(
        instruction=instruction, context="", source_document="", report=report,
    )

    assert findings == []


# ===========================================================================
# merge_conflicts -- the applied_anyway invariant and dedup/severity merge
# ===========================================================================
def test_applied_anyway_is_always_true_even_with_critical_findings():
    instruction = parse_revision_instruction("Tarihi 01.01.2027 olarak değiştir.")
    report = _report_for(WELL_FORMED_DRAFT)
    findings = detect_conflicts_deterministic(
        instruction=instruction, context="",
        source_document="Bu evrak 30.07.2026 tarihlidir.", report=report,
    )

    result = merge_conflicts(findings, [])
    assert result.applied_anyway is True


def test_no_findings_does_not_force_approval():
    result = merge_conflicts([], [])
    assert result.requires_human_approval is False
    assert result.conflicts == []


def test_a_major_or_critical_finding_forces_approval_but_a_minor_one_alone_does_not():
    instruction = parse_revision_instruction("Muhatabı Ankara Valiliği olarak yaz.")
    draft = WELL_FORMED_DRAFT.replace(
        "Sayın Makam,\n\n", "Sayın Makam,\n\nAnkara Valiliği'ne bilgi verilmiştir.\n\n"
    )
    report = _report_for(draft, instructions=instruction.raw)
    minor_only = detect_conflicts_deterministic(
        instruction=instruction, context="", source_document="", report=report,
    )
    assert all(f.severity == "minor" for f in minor_only)

    result = merge_conflicts(minor_only, [])
    assert result.requires_human_approval is False


def test_duplicate_findings_from_both_layers_are_deduped_keeping_higher_severity():
    """A genuine duplicate: both layers describe the exact same conflict
    (identical detail text), just at different severities -- the higher one
    wins and only one finding surfaces."""
    from app.ai.revision.conflict import ConflictFinding

    deterministic = [
        ConflictFinding(
            kind="mevzuat_dayanaksiz", severity="major", detail="aynı çelişki",
            instruction_fragment="x", source="deterministic",
        )
    ]
    llm = [
        ConflictFinding(
            kind="mevzuat_dayanaksiz", severity="critical", detail="aynı çelişki",
            instruction_fragment="x", source="llm",
        )
    ]

    result = merge_conflicts(deterministic, llm)
    assert len(result.conflicts) == 1
    assert result.conflicts[0].severity == "critical"


def test_two_distinct_conflicts_of_the_same_kind_both_surface():
    """C28 regression: before this, every finding from one
    detect_conflicts_deterministic call shared the same
    instruction_fragment (computed once per instruction, not per-finding),
    so two genuinely different conflicts of the same kind -- e.g. a date
    contradiction and a separate sayı contradiction, both "kaynak_celiskisi"
    -- collapsed onto the same dedup key and one was silently discarded."""
    from app.ai.revision.conflict import ConflictFinding

    date_conflict = ConflictFinding(
        kind="kaynak_celiskisi", severity="critical",
        detail="Talimattaki tarih ('12.05.2026') kaynak evraktaki tarih ('01.01.2026') ile çelişiyor.",
        instruction_fragment="aynı talimat", source="deterministic",
    )
    number_conflict = ConflictFinding(
        kind="kaynak_celiskisi", severity="critical",
        detail="Talimattaki sayı ('E-999') kaynak evraktaki sayı ('E-123') ile çelişiyor.",
        instruction_fragment="aynı talimat", source="deterministic",
    )

    result = merge_conflicts([date_conflict, number_conflict], [])

    assert len(result.conflicts) == 2
    details = {finding.detail for finding in result.conflicts}
    assert date_conflict.detail in details
    assert number_conflict.detail in details


# ===========================================================================
# assess_conflicts_llm -- degrades on failure, never raises
# ===========================================================================
@pytest.mark.asyncio
async def test_a_successful_llm_call_returns_findings(fake_llm):
    fake_llm.generate_structured_return = ConflictAssessment(
        conflicts=[
            LlmConflictFinding(
                kind="mevzuat_celiskisi", severity="major",
                detail="Talimat mevzuatın X hükmüyle çelişiyor.", evidence="Madde 5",
            )
        ],
        rationale="Test rationale.",
    )
    agent = ConflictAuditorAgent(fake_llm)

    findings = await assess_conflicts_llm(
        agent, instruction="test talimatı", revised_draft=WELL_FORMED_DRAFT,
        context="", source_document="",
    )

    assert len(findings) == 1
    assert findings[0].source == "llm"
    assert findings[0].kind == "mevzuat_celiskisi"


@pytest.mark.asyncio
async def test_a_provider_error_degrades_to_an_empty_list(fake_llm):
    fake_llm.generate_structured_side_effect = [RuntimeError("provider down")]
    agent = ConflictAuditorAgent(fake_llm)

    findings = await assess_conflicts_llm(
        agent, instruction="test talimatı", revised_draft=WELL_FORMED_DRAFT,
        context="", source_document="",
    )

    assert findings == []
