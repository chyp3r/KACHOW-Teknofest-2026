"""Unit tests for the reasoning-level preset resolver.

The core contract under test: BALANCED must resolve to exactly today's
pre-existing draft_graph.py defaults (2 attempts, 2048 tokens), since that is
what makes adding this feature a zero-regression change for every caller that
never sets a reasoning level.
"""

import pytest

from app.ai.reasoning_levels import get_reasoning_level_preset
from app.core.enums.reasoning_level import ReasoningLevel


def test_balanced_matches_todays_pre_existing_defaults():
    preset = get_reasoning_level_preset(ReasoningLevel.BALANCED)

    assert preset.model_tier == "quality"
    assert preset.reasoning is False
    assert preset.max_draft_attempts == 2
    assert preset.judge_enabled is None
    assert preset.draft_max_tokens == 2048
    assert preset.timeout_multiplier == 1.0


def test_fast_trades_quality_for_speed_without_a_new_model():
    preset = get_reasoning_level_preset(ReasoningLevel.FAST)

    assert preset.model_tier == "fast"
    assert preset.reasoning is False
    assert preset.max_draft_attempts == 1
    assert preset.judge_enabled is False
    assert preset.timeout_multiplier < 1.0


def test_deep_reuses_the_quality_model_and_spends_more_compute():
    preset = get_reasoning_level_preset(ReasoningLevel.DEEP)

    # Never a third model tier: only "fast" or "quality" are valid.
    assert preset.model_tier == "quality"
    assert preset.reasoning is True
    assert preset.max_draft_attempts > 2
    assert preset.judge_enabled is True
    # Thinking-mode tokens share num_predict with the final answer, so deep
    # needs more budget than balanced, not the same.
    assert preset.draft_max_tokens > 2048
    assert preset.timeout_multiplier > 1.0


@pytest.mark.parametrize("value", [None, "", "garbage", "FAST_TYPO", 42])
def test_unknown_or_missing_level_falls_back_to_balanced_without_raising(value):
    preset = get_reasoning_level_preset(value)

    assert preset.level == ReasoningLevel.BALANCED


@pytest.mark.parametrize("value", ["fast", "balanced", "deep"])
def test_plain_string_values_resolve_like_the_enum(value):
    """Requests arrive as plain strings from checkpointed LangGraph state."""
    preset = get_reasoning_level_preset(value)

    assert preset.level == ReasoningLevel(value)
