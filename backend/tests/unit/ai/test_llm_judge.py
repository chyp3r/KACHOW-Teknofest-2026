"""Unit tests for the hybrid quality gate: judge_draft() and merge_verdicts()."""

import asyncio

import pytest

from app.ai.agents.judge import JudgeAgent
from app.ai.verification.draft_verifier import MIN_AUTOMATED_CONFIDENCE_SCORE, VerificationReport
from app.ai.verification.llm_judge import (
    DraftJudgeVerdict,
    JudgeFinding,
    judge_draft,
    merge_verdicts,
)
from app.ai.verification.missing_info import InfoQuestion


def _verdict(**overrides) -> DraftJudgeVerdict:
    fields = dict(
        addresses_request=True,
        register_ok=True,
        closing_direction="arz",
        closing_correct=True,
        muhatap_consistent=True,
        score=90.0,
        findings=[],
        rationale="Taslak talebi karşılıyor ve resmî üsluba uygun.",
    )
    fields.update(overrides)
    return DraftJudgeVerdict(**fields)


def _report(**overrides) -> VerificationReport:
    fields = dict(
        confidence_score=90.0,
        requires_human_approval=False,
        unsupported_claims=[],
        missing_structure=[],
        placeholder_count=0,
        evaluation_notes="ok",
    )
    fields.update(overrides)
    return VerificationReport(**fields)


# ==========================================
# judge_draft()
# ==========================================
@pytest.mark.asyncio
async def test_judge_draft_returns_the_verdict_on_success(fake_fast_llm):
    agent = JudgeAgent(fake_fast_llm)
    verdict = _verdict()

    async def fake_run_structured(**kwargs):
        return verdict

    agent.run_structured = fake_run_structured

    result = await judge_draft(
        agent, draft="Sayın Makam, arz ederim.", brief="brief", correspondence_type="cover_letter",
        instructions="",
    )

    assert result is verdict


@pytest.mark.asyncio
async def test_judge_draft_degrades_to_none_on_timeout(fake_fast_llm):
    agent = JudgeAgent(fake_fast_llm)

    async def hangs(**kwargs):
        await asyncio.sleep(10)

    agent.run_structured = hangs

    result = await judge_draft(
        agent, draft="x", brief="b", correspondence_type="cover_letter", instructions="",
        timeout_s=0.01,
    )

    assert result is None


@pytest.mark.asyncio
async def test_judge_draft_degrades_to_none_on_provider_exception(fake_fast_llm):
    agent = JudgeAgent(fake_fast_llm)

    async def raises(**kwargs):
        raise RuntimeError("provider unavailable")

    agent.run_structured = raises

    result = await judge_draft(
        agent, draft="x", brief="b", correspondence_type="cover_letter", instructions=""
    )

    assert result is None


@pytest.mark.asyncio
async def test_judge_draft_rejects_a_verdict_that_echoes_the_draft(fake_fast_llm):
    agent = JudgeAgent(fake_fast_llm)
    draft = (
        "Sayın Genel Müdürlük makamına arz ederim ki bu evrak çok önemli bir "
        "konuyu ele almaktadır ve gerekli işlemlerin yapılmasını rica ederim"
    )
    # Rationale built almost entirely out of the draft's own tokens.
    echoing_verdict = _verdict(rationale=draft)

    async def fake_run_structured(**kwargs):
        return echoing_verdict

    agent.run_structured = fake_run_structured

    result = await judge_draft(
        agent, draft=draft, brief="b", correspondence_type="cover_letter", instructions=""
    )

    assert result is None


# ==========================================
# merge_verdicts()
# ==========================================
def test_merge_computes_weighted_average_when_judge_available():
    combined = merge_verdicts(_report(confidence_score=80.0), _verdict(score=60.0))

    assert combined.combined_score == round(0.6 * 80.0 + 0.4 * 60.0, 1)
    assert combined.judge_available is True


def test_merge_falls_back_to_deterministic_score_when_judge_unavailable():
    combined = merge_verdicts(_report(confidence_score=85.0), None)

    assert combined.combined_score == 85.0
    assert combined.judge_available is False
    assert "kullanılamadı" in combined.notes


def test_critical_finding_caps_score_and_forces_human_approval():
    verdict = _verdict(
        score=95.0,
        findings=[
            JudgeFinding(
                kind="kapanis", severity="critical", detail="Yanlış kapanış yönü.",
                suggested_fix="Rica ederim yerine arz ederim kullan.",
            )
        ],
    )
    combined = merge_verdicts(_report(confidence_score=95.0), verdict)

    assert combined.combined_score < MIN_AUTOMATED_CONFIDENCE_SCORE
    assert combined.requires_human_approval is True
    assert combined.requires_revision is True
    assert any(item.kind == "judge:kapanis" for item in combined.repair_items)


def test_critical_finding_of_a_non_revisable_kind_still_forces_approval_but_no_repair_item():
    """'mevzuat' and 'tutarlilik' findings can't be fixed by a text-only
    revision pass -- they should still gate approval, but not produce a
    repair instruction the reviser can't actually act on."""
    verdict = _verdict(
        score=95.0,
        findings=[
            JudgeFinding(
                kind="mevzuat", severity="critical", detail="Yanlış atıf.",
                suggested_fix="Farklı madde kullan.",
            )
        ],
    )
    combined = merge_verdicts(_report(confidence_score=95.0), verdict)

    assert combined.requires_human_approval is True
    assert not any(item.source == "judge" for item in combined.repair_items)


def test_addresses_request_false_forces_approval_regardless_of_score():
    verdict = _verdict(score=95.0, addresses_request=False)
    combined = merge_verdicts(_report(confidence_score=95.0), verdict)

    assert combined.requires_human_approval is True
    assert any(item.kind == "judge:talep" for item in combined.repair_items)


def test_deterministic_defects_become_revisable_repair_items():
    report = _report(
        confidence_score=50.0,
        missing_structure=["Konu satırı"],
        requires_human_approval=True,
    )
    combined = merge_verdicts(report, None)

    assert combined.requires_revision is True
    assert any(item.kind == "missing_structure" for item in combined.repair_items)


def test_missing_information_passes_through_unchanged():
    questions = [InfoQuestion(key="muhatap", label="[MUHATAP]")]
    combined = merge_verdicts(_report(), _verdict(), missing_information=questions)

    assert combined.missing_information == questions


def test_clean_draft_and_verdict_requires_neither_revision_nor_approval():
    combined = merge_verdicts(_report(), _verdict())

    assert combined.requires_revision is False
    assert combined.requires_human_approval is False
