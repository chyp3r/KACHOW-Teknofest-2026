"""Unit tests for the `revise` intent and the fused-probability decision bands.

`revise` is gated on an active draft the same way a document-only rule is
gated on an attached document (`EvidenceRule.requires_active_draft`). Once
the fused probability is computed, `resolve_plan` bands on it: a winner at or
above `tau_high` commits outright, the band down to `tau_low` breaks the tie
with a fast-tier model call when one is available, and anything below that
asks the user instead -- see `resolve_plan`'s docstring.

The band tests below patch `router_fusion.predict_proba` to fixed
distributions rather than relying on the real fitted `ROUTER_WEIGHTS` --
`resolve_plan`'s routing logic (which band does what) is what's under test
here, independent of whatever a future refit's exact coefficients produce.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.policy import get_policy
from app.ai.session.focus import DraftVersion, SessionFocus
from app.ai.workflows.intent_scorer import score_intents
from app.ai.workflows.planner import (
    PLAN_BY_INTENT,
    _build_clarify_decision,
    _try_resolve_pending_clarification,
    resolve_plan,
)

_ACTIVE_DRAFT = DraftVersion(
    version=1, text="Sayın Makam, ...", correspondence_type="cover_letter",
    confidence_score=80.0, created_from="draft",
)
_FOCUS_WITH_DRAFT = SessionFocus(active_draft=_ACTIVE_DRAFT, draft_history=(_ACTIVE_DRAFT,))

_TAU_HIGH = get_policy().intent.tau_high
_TAU_LOW = get_policy().intent.tau_low


def _flat_above(intent: str, probability: float) -> dict[str, float]:
    """A probability dict with `intent` at `probability` and the rest sharing what's left."""
    remainder = (1.0 - probability) / 3
    probs = {name: remainder for name in ("draft", "analyze", "assist", "revise")}
    probs[intent] = probability
    return probs


# ===========================================================================
# revise gated on an active draft
# ===========================================================================
def test_revise_rule_is_silent_without_an_active_draft():
    scores = score_intents("Bu taslağı revize et lütfen.", None, has_active_draft=False)
    assert "revise" not in scores.scores


def test_revise_rule_fires_with_an_active_draft():
    scores = score_intents("Bu taslağı revize et lütfen.", None, has_active_draft=True)
    assert scores.scores.get("revise", 0.0) > 0


@pytest.mark.asyncio
async def test_revise_resolves_with_an_active_draft():
    decision = await resolve_plan(
        "Bu taslağı revize et lütfen.", None, focus=_FOCUS_WITH_DRAFT
    )
    assert decision.intent == "revise"
    assert decision.steps == PLAN_BY_INTENT["revise"]


@pytest.mark.asyncio
async def test_a_short_affirmative_continues_a_revise_offer():
    decision = await resolve_plan(
        "evet", None, previous_intent="revise", focus=_FOCUS_WITH_DRAFT
    )
    assert decision.intent == "revise"


# ===========================================================================
# resolve_plan: the fused-probability decision bands
# ===========================================================================
@pytest.mark.asyncio
async def test_a_probability_at_or_above_tau_high_commits_without_a_model_call():
    classify = AsyncMock(return_value="assist")
    with patch(
        "app.ai.workflows.planner.predict_proba",
        return_value=_flat_above("draft", _TAU_HIGH + 0.05),
    ), patch("app.ai.workflows.planner.classify_intent_with_model", new=classify):
        decision = await resolve_plan("Bu evrağa bir cevap yazısı hazırla.", None, llm_client=MagicMock())

    assert decision.intent == "draft"
    assert decision.source == "fused"
    classify.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_contested_probability_breaks_the_tie_with_the_model_when_available():
    classify = AsyncMock(return_value="analyze")
    contested = _flat_above("draft", (_TAU_HIGH + _TAU_LOW) / 2)
    with patch("app.ai.workflows.planner.predict_proba", return_value=contested), patch(
        "app.ai.workflows.planner.classify_intent_with_model", new=classify
    ):
        decision = await resolve_plan("Bununla ilgili bir şeyler yap.", None, llm_client=MagicMock())

    assert decision.intent == "analyze"
    assert decision.source == "model"
    classify.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_contested_probability_without_a_model_client_asks_instead():
    contested = _flat_above("draft", (_TAU_HIGH + _TAU_LOW) / 2)
    with patch("app.ai.workflows.planner.predict_proba", return_value=contested):
        decision = await resolve_plan("Bununla ilgili bir şeyler yap.", None, llm_client=None)

    assert decision.intent == "clarify"
    assert decision.source == "clarify"


@pytest.mark.asyncio
async def test_a_probability_below_tau_low_asks_even_with_a_model_client_available():
    classify = AsyncMock(return_value="assist")
    flat = {name: 0.25 for name in ("draft", "analyze", "assist", "revise")}
    with patch("app.ai.workflows.planner.predict_proba", return_value=flat), patch(
        "app.ai.workflows.planner.classify_intent_with_model", new=classify
    ):
        decision = await resolve_plan("Bunu hallet.", "doc-1", llm_client=MagicMock())

    assert decision.source == "clarify"
    classify.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unambiguous_short_imperative_resolves_to_draft_for_real():
    """The K2 regression this whole fusion layer exists to fix: an explicit,
    unambiguous imperative used to lose to the generic short-message
    structural hint by a margin just under the old ladder's threshold and
    fall through to a clarifying question it never should have asked. No
    mocking here -- this exercises the real fitted `ROUTER_WEIGHTS`.
    """
    decision = await resolve_plan("Cevap yaz.", None)

    assert decision.intent == "draft"
    assert decision.source != "clarify"


# ===========================================================================
# _build_clarify_decision (whitebox)
# ===========================================================================
def test_clarify_decision_offers_the_top_two_fused_probabilities():
    ranked = [("revise", 0.4), ("draft", 0.3), ("assist", 0.2), ("analyze", 0.1)]
    decision = _build_clarify_decision(ranked)

    assert decision.intent == "clarify"
    options = [opt["intent"] for opt in decision.clarification["options"]]
    assert options == ["revise", "draft"]
    assert decision.confidence == 0.4


# ===========================================================================
# _try_resolve_pending_clarification
# ===========================================================================
_PENDING = {
    "question": "Bunu taslak hazırlama isteği olarak mı, yoksa genel bir soru olarak mı ele almalıyım?",
    "options": [
        {"intent": "draft", "label": "bir taslak hazırlama isteği"},
        {"intent": "assist", "label": "genel bir soru veya sohbet"},
    ],
}


def test_a_bare_affirmative_selects_the_leading_option():
    decision = _try_resolve_pending_clarification("evet", _PENDING)
    assert decision is not None
    assert decision.intent == "draft"
    assert decision.source == "clarification_resolved"
    assert decision.confidence == 1.0


def test_naming_the_second_option_selects_it_instead():
    decision = _try_resolve_pending_clarification(
        "Genel bir soru veya sohbet demek istemiştim.", _PENDING
    )
    assert decision is not None
    assert decision.intent == "assist"


def test_an_unrelated_reply_does_not_force_a_resolution():
    decision = _try_resolve_pending_clarification(
        "Aslında başka bir şey soracaktım, hava nasıl?", _PENDING
    )
    assert decision is None


def test_no_pending_clarification_returns_none():
    assert _try_resolve_pending_clarification("evet", None) is None
    assert _try_resolve_pending_clarification("evet", {}) is None


@pytest.mark.asyncio
async def test_resolve_plan_checks_pending_clarification_before_fusion_runs():
    focus = SessionFocus(pending_clarification=_PENDING)
    classify = AsyncMock(return_value="assist")

    decision = await resolve_plan("evet", None, llm_client=classify, focus=focus)

    assert decision.intent == "draft"
    assert decision.source == "clarification_resolved"
    classify.assert_not_awaited()
