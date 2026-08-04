"""Proof that token usage is actually measured (B2), not guessed.

`LLM_TOKENS` used to be a declared Prometheus collector nobody incremented --
context budgeting was managed by char-count and turn-count proxies with no
visibility into whether a prompt was close to overflowing the model's
context window. These tests exercise the real wiring (BaseLLMClient.count_tokens
plus BaseAgent.run/run_structured calling it) end to end and assert the
metric moves by a real, non-zero amount.
"""

import pytest

from app.ai.agents.base import BaseAgent
from app.observability.ai_metrics import LLM_TOKENS


def _counter_value(agent: str, kind: str) -> float:
    return LLM_TOKENS.labels(agent=agent, kind=kind)._value.get()


def test_count_tokens_is_zero_for_blank_text(fake_llm):
    assert fake_llm.count_tokens("") == 0
    assert fake_llm.count_tokens("   \n\t  ") == 0


def test_count_tokens_scales_with_text_length(fake_llm):
    short = fake_llm.count_tokens("Merhaba dünya.")
    long = fake_llm.count_tokens("Merhaba dünya. " * 20)

    assert short > 0
    assert long > short


@pytest.mark.asyncio
async def test_llm_tokens_increments_after_a_successful_run(fake_llm):
    fake_llm.generate_return = "Bu, birden fazla kelime içeren bir test yanıtıdır."

    agent = BaseAgent(
        llm_client=fake_llm,
        name="MetricsProofAgent",
        description="test",
        system_prompt="Sen bir test ajanısın.",
    )

    before_prompt = _counter_value("MetricsProofAgent", "prompt")
    before_completion = _counter_value("MetricsProofAgent", "completion")

    await agent.run(messages="Uzunca bir kullanıcı mesajı buraya gelsin lütfen.")

    assert _counter_value("MetricsProofAgent", "prompt") > before_prompt
    assert _counter_value("MetricsProofAgent", "completion") > before_completion


@pytest.mark.asyncio
async def test_llm_tokens_increments_after_a_successful_structured_run(fake_llm):
    from pydantic import BaseModel

    class _Schema(BaseModel):
        value: str

    fake_llm.generate_structured_return = _Schema(value="ok")

    agent = BaseAgent(
        llm_client=fake_llm,
        name="StructuredMetricsProofAgent",
        description="test",
        system_prompt="Sen bir test ajanısın.",
    )

    before_prompt = _counter_value("StructuredMetricsProofAgent", "prompt")
    before_completion = _counter_value("StructuredMetricsProofAgent", "completion")

    await agent.run_structured(messages="Girdi verisi.", response_model=_Schema)

    assert _counter_value("StructuredMetricsProofAgent", "prompt") > before_prompt
    assert _counter_value("StructuredMetricsProofAgent", "completion") > before_completion
