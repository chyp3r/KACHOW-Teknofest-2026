"""Unit tests for the deterministic-diff + single-LLM-call style miner
(Faz C3, #187)."""

from app.ai.training.dataset import PreferencePair
from app.ai.training.style_miner import MIN_FEEDBACK_SAMPLES, mine_style


def _pair(chosen=None, rejected=None, index=0) -> PreferencePair:
    return PreferencePair(
        source="explicit_feedback",
        source_feedback_id=f"fb-{index}",
        source_draft_id=None,
        prompt_context="",
        chosen=chosen,
        rejected=rejected,
        weight=1.0,
        pair_hash=f"hash-{index}",
    )


def _liked_and_disliked_pairs(count: int) -> list[PreferencePair]:
    pairs = []
    for i in range(count):
        if i % 2 == 0:
            pairs.append(_pair(chosen="Sayın Makam, arz ederim.", index=i))
        else:
            pairs.append(_pair(rejected="selam nasılsın, tamamdır.", index=i))
    return pairs


async def test_mining_is_skipped_below_the_minimum_sample_threshold(fake_fast_llm):
    pairs = _liked_and_disliked_pairs(MIN_FEEDBACK_SAMPLES - 1)

    result = await mine_style(fake_fast_llm, pairs)

    assert result is None
    assert fake_fast_llm.generate_structured_calls == []


async def test_mining_makes_exactly_one_llm_call_regardless_of_sample_count(fake_fast_llm):
    fake_fast_llm.generate_structured_return = type(
        "R", (), {"style_rules": ["Kısa cümleler kullan."], "avoided_patterns": ["Argo kullanma."]}
    )()
    pairs = _liked_and_disliked_pairs(MIN_FEEDBACK_SAMPLES + 20)

    result = await mine_style(fake_fast_llm, pairs)

    assert len(fake_fast_llm.generate_structured_calls) == 1
    assert result is not None
    assert result.style_rules == ("Kısa cümleler kullan.",)
    assert result.avoided_patterns == ("Argo kullanma.",)
    assert result.sample_count == MIN_FEEDBACK_SAMPLES + 20


async def test_mined_rules_are_capped_at_ten_even_if_the_model_returns_more(fake_fast_llm):
    fake_fast_llm.generate_structured_return = type(
        "R",
        (),
        {
            "style_rules": [f"Kural {i}" for i in range(15)],
            "avoided_patterns": [f"Kaçın {i}" for i in range(15)],
        },
    )()
    pairs = _liked_and_disliked_pairs(MIN_FEEDBACK_SAMPLES)

    result = await mine_style(fake_fast_llm, pairs)

    assert len(result.style_rules) == 10
    assert len(result.avoided_patterns) == 10


async def test_prompt_never_carries_more_than_the_capped_examples_per_side(fake_fast_llm):
    fake_fast_llm.generate_structured_return = type(
        "R", (), {"style_rules": [], "avoided_patterns": []}
    )()
    pairs = _liked_and_disliked_pairs(MIN_FEEDBACK_SAMPLES + 40)

    await mine_style(fake_fast_llm, pairs)

    prompt = fake_fast_llm.generate_structured_calls[0]["messages"][-1]["content"]
    assert prompt.count("[Beğenilen #") <= 6
    assert prompt.count("[Beğenilmeyen #") <= 6
