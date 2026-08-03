"""Reasoning-level presets: a user-selectable speed-vs-quality tradeoff.

Three levels, all built from the two LLM tiers and knobs that already exist
in this codebase (``get_llm_client``/``get_fast_llm_client``, Ollama's
``reasoning`` kwarg, the draft reflexion loop's attempt cap and judge gate) --
no level introduces a third resident model. ``deep`` trades wall-clock time
for quality by spending more inference-time compute on the *existing*
quality-tier model (thinking mode, extra reflexion passes, a mandatory judge
pass); ``fast`` trades quality for speed by routing free-text generation
through the already-warm fast-tier model instead. ``balanced`` reproduces
today's hardcoded draft_graph.py defaults exactly, so it carries zero
behavioural change.
"""

from dataclasses import dataclass
from typing import Literal, Optional

from app.core.enums.reasoning_level import ReasoningLevel

#: Today's hardcoded draft_graph.py defaults, kept here as the single source
#: of truth so BALANCED is provably identical to pre-reasoning-level behavior.
_BALANCED_DRAFT_MAX_TOKENS = 2048
_BALANCED_MAX_DRAFT_ATTEMPTS = 2


@dataclass(frozen=True)
class ReasoningLevelPreset:
    """Resolved knobs for a single reasoning level."""

    level: ReasoningLevel
    label_tr: str
    model_tier: Literal["fast", "quality"]
    reasoning: bool
    max_draft_attempts: int
    #: None means "respect settings.DRAFT_JUDGE_ENABLED"; True/False forces it.
    judge_enabled: Optional[bool]
    draft_max_tokens: int
    timeout_multiplier: float


_PRESETS: dict[ReasoningLevel, ReasoningLevelPreset] = {
    ReasoningLevel.FAST: ReasoningLevelPreset(
        level=ReasoningLevel.FAST,
        label_tr="Hızlı",
        model_tier="fast",
        reasoning=False,
        max_draft_attempts=1,
        judge_enabled=False,
        draft_max_tokens=_BALANCED_DRAFT_MAX_TOKENS,
        timeout_multiplier=0.6,
    ),
    ReasoningLevel.BALANCED: ReasoningLevelPreset(
        level=ReasoningLevel.BALANCED,
        label_tr="Dengeli",
        model_tier="quality",
        reasoning=False,
        max_draft_attempts=_BALANCED_MAX_DRAFT_ATTEMPTS,
        judge_enabled=None,
        draft_max_tokens=_BALANCED_DRAFT_MAX_TOKENS,
        timeout_multiplier=1.0,
    ),
    ReasoningLevel.DEEP: ReasoningLevelPreset(
        level=ReasoningLevel.DEEP,
        label_tr="Derin",
        model_tier="quality",
        reasoning=True,
        max_draft_attempts=3,
        judge_enabled=True,
        # Thinking-mode's <think>...</think> tokens share num_predict with the
        # final answer; the balanced budget is too tight once reasoning=True.
        draft_max_tokens=3072,
        timeout_multiplier=1.8,
    ),
}


def get_reasoning_level_preset(level: "ReasoningLevel | str | None") -> ReasoningLevelPreset:
    """Resolve a reasoning level to its preset, defaulting safely to BALANCED.

    ``level`` may arrive from checkpointed LangGraph state or a client
    request, so an unknown, missing, or malformed value must never raise --
    it silently falls back to today's default behaviour instead.
    """
    if level is None:
        return _PRESETS[ReasoningLevel.BALANCED]
    try:
        resolved = ReasoningLevel(level)
    except ValueError:
        return _PRESETS[ReasoningLevel.BALANCED]
    return _PRESETS[resolved]


__all__ = ["ReasoningLevelPreset", "get_reasoning_level_preset"]
