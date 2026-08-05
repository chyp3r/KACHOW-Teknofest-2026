"""Unit tests for the guardrail nuance layer's LLM judge."""

import asyncio

import pytest

from app.ai.agents.guardrail_judge import GuardrailJudgeAgent
from app.ai.guardrails.llm_nuance import (
    GuardrailJudgeVerdict,
    judge_input_sensitivity,
    judge_output_leakage,
)


def _verdict(**overrides) -> GuardrailJudgeVerdict:
    fields = dict(sensitive=False, confidence=0.9, reason="Sıradan resmi yazışma içeriği.")
    fields.update(overrides)
    return GuardrailJudgeVerdict(**fields)


# ==========================================
# judge_input_sensitivity()
# ==========================================
@pytest.mark.asyncio
async def test_judge_input_sensitivity_returns_the_verdict_on_success(fake_fast_llm):
    agent = GuardrailJudgeAgent(fake_fast_llm)
    verdict = _verdict(sensitive=True, reason="İzin talebinde tıbbi tanı detayı geçiyor.")

    async def fake_run_structured(**kwargs):
        return verdict

    agent.run_structured = fake_run_structured

    result = await judge_input_sensitivity(agent, text="izin talebi metni")

    assert result is verdict


@pytest.mark.asyncio
async def test_judge_input_sensitivity_returns_none_for_empty_text(fake_fast_llm):
    agent = GuardrailJudgeAgent(fake_fast_llm)
    result = await judge_input_sensitivity(agent, text="   ")
    assert result is None


@pytest.mark.asyncio
async def test_judge_input_sensitivity_degrades_to_none_on_timeout(fake_fast_llm):
    agent = GuardrailJudgeAgent(fake_fast_llm)

    async def hangs(**kwargs):
        await asyncio.sleep(10)

    agent.run_structured = hangs

    result = await judge_input_sensitivity(agent, text="belge metni", timeout_s=0.01)

    assert result is None


@pytest.mark.asyncio
async def test_judge_input_sensitivity_degrades_to_none_on_provider_exception(fake_fast_llm):
    agent = GuardrailJudgeAgent(fake_fast_llm)

    async def raises(**kwargs):
        raise RuntimeError("provider unavailable")

    agent.run_structured = raises

    result = await judge_input_sensitivity(agent, text="belge metni")

    assert result is None


@pytest.mark.asyncio
async def test_judge_input_sensitivity_is_disabled_via_settings(fake_fast_llm, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "GUARDRAIL_JUDGE_ENABLED", False)
    agent = GuardrailJudgeAgent(fake_fast_llm)
    called = False

    async def fake_run_structured(**kwargs):
        nonlocal called
        called = True
        return _verdict()

    agent.run_structured = fake_run_structured

    result = await judge_input_sensitivity(agent, text="belge metni")

    assert result is None
    assert called is False


# ==========================================
# Anti-echo guard
# ==========================================
@pytest.mark.asyncio
async def test_a_verdict_that_echoes_the_judged_document_is_rejected(fake_fast_llm):
    agent = GuardrailJudgeAgent(fake_fast_llm)
    text = (
        "Başvuran kişinin ciddi bir sağlık sorunu bulunduğu ve bu nedenle "
        "uzun süreli izin talep ettiği belirtilmektedir"
    )
    # Reason built almost entirely out of the judged text's own tokens --
    # this is meant to catch a judge re-emitting content, not judging it.
    echoing_verdict = _verdict(sensitive=True, reason=text)

    async def fake_run_structured(**kwargs):
        return echoing_verdict

    agent.run_structured = fake_run_structured

    result = await judge_input_sensitivity(agent, text=text)

    assert result is None


@pytest.mark.asyncio
async def test_a_short_reason_is_not_treated_as_an_echo(fake_fast_llm):
    """A genuinely short, non-overlapping reason must not be rejected just
    because there are too few tokens to compute a meaningful overlap."""
    agent = GuardrailJudgeAgent(fake_fast_llm)
    verdict = _verdict(sensitive=True, reason="Tıbbi detay içeriyor.")

    async def fake_run_structured(**kwargs):
        return verdict

    agent.run_structured = fake_run_structured

    result = await judge_input_sensitivity(agent, text="tamamen alakasız bir belge metni burada")

    assert result is verdict


@pytest.mark.asyncio
async def test_a_malformed_verdict_does_not_crash_the_caller(fake_fast_llm):
    """Regression: the echo check used to run outside judge_input_sensitivity's
    own try/except, so a verdict whose `reason` wasn't a real string (e.g. a
    misbehaving mock, or any provider quirk) crashed the caller instead of
    degrading to None like every other failure mode."""
    agent = GuardrailJudgeAgent(fake_fast_llm)

    class _NotAVerdict:
        reason = object()  # not a str -- must not crash _fold()/_reject_echo()

    async def fake_run_structured(**kwargs):
        return _NotAVerdict()

    agent.run_structured = fake_run_structured

    result = await judge_input_sensitivity(agent, text="belge metni")

    assert result is None


# ==========================================
# judge_output_leakage()
# ==========================================
@pytest.mark.asyncio
async def test_judge_output_leakage_returns_the_verdict_on_success(fake_fast_llm):
    agent = GuardrailJudgeAgent(fake_fast_llm)
    verdict = _verdict(sensitive=True, reason="Yanıt, kaynağın kimliğini dolaylı olarak ifşa ediyor.")

    async def fake_run_structured(**kwargs):
        return verdict

    agent.run_structured = fake_run_structured

    result = await judge_output_leakage(agent, reply="işte yanıt", source_summary="bir özet")

    assert result is verdict


@pytest.mark.asyncio
async def test_judge_output_leakage_returns_none_for_empty_reply(fake_fast_llm):
    agent = GuardrailJudgeAgent(fake_fast_llm)
    result = await judge_output_leakage(agent, reply="", source_summary="özet")
    assert result is None
