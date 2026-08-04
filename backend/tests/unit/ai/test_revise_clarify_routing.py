"""Unit tests for the `revise` intent and the clarify-vs-guess decision.

`revise` is gated on an active draft the same way a document-only rule is
gated on an attached document (`EvidenceRule.requires_active_draft`). Once
neither the lexical nor the semantic rung is decisive, the ladder no longer
escalates everything to the model: a cheap contested candidate (`assist`) is
guessed, an expensive one (`draft`/`revise`) triggers a deterministic,
LLM-free clarifying question instead -- see `resolve_plan`'s docstring.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.session.focus import DraftVersion, SessionFocus
from app.ai.workflows.intent_scorer import score_intents
from app.ai.workflows.planner import (
    PLAN_BY_INTENT,
    _build_clarify_decision,
    _try_resolve_pending_clarification,
    resolve_plan,
    resolve_plan_deterministic,
)

_ACTIVE_DRAFT = DraftVersion(
    version=1, text="Sayın Makam, ...", correspondence_type="cover_letter",
    confidence_score=80.0, created_from="draft",
)
_FOCUS_WITH_DRAFT = SessionFocus(active_draft=_ACTIVE_DRAFT, draft_history=(_ACTIVE_DRAFT,))


# ===========================================================================
# revise gated on an active draft
# ===========================================================================
def test_revise_rule_is_silent_without_an_active_draft():
    scores = score_intents("Bu taslağı revize et lütfen.", None, has_active_draft=False)
    assert "revise" not in scores.scores


def test_revise_rule_fires_with_an_active_draft():
    scores = score_intents("Bu taslağı revize et lütfen.", None, has_active_draft=True)
    assert scores.scores.get("revise", 0.0) > 0


def test_revise_resolves_decisively_with_an_active_draft():
    decision = resolve_plan_deterministic(
        "Bu taslağı revize et lütfen.", None, has_active_draft=True
    )
    assert decision is not None
    assert decision.intent == "revise"
    assert decision.steps == PLAN_BY_INTENT["revise"]


def test_a_revise_phrase_without_an_active_draft_abstains():
    decision = resolve_plan_deterministic(
        "Bu taslağı revize et lütfen.", None, has_active_draft=False
    )
    assert decision is None


def test_a_short_affirmative_continues_a_revise_offer():
    decision = resolve_plan_deterministic(
        "evet", None, previous_intent="revise", has_active_draft=True
    )
    assert decision is not None
    assert decision.intent == "revise"
    assert decision.source == "continuation"


# ===========================================================================
# resolve_plan: clarify vs. cheap guess once both rungs abstain
# ===========================================================================
@pytest.mark.asyncio
async def test_a_contested_expensive_candidate_triggers_clarify_not_the_model():
    with patch(
        "app.ai.workflows.planner.classify_intent_with_model",
        new=AsyncMock(return_value="assist"),
    ) as classify:
        decision = await resolve_plan(
            "Kısalt.",
            None,
            llm_client=MagicMock(),
            focus=_FOCUS_WITH_DRAFT,
        )

    assert decision.intent == "clarify"
    assert decision.source == "clarify"
    assert decision.clarification is not None
    assert decision.clarification["question"]
    assert {opt["intent"] for opt in decision.clarification["options"]} == {"revise", "assist"}
    classify.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_contested_cheap_candidate_is_guessed_not_asked_about():
    with patch(
        "app.ai.workflows.planner.classify_intent_with_model",
        new=AsyncMock(return_value="draft"),
    ) as classify:
        decision = await resolve_plan(
            "Bu evrak hakkında ne dersin, taslak da hazirla.",
            "doc-1",
            llm_client=MagicMock(),
        )

    assert decision.intent == "assist"
    assert decision.source == "guessed_cheap"
    classify.assert_not_awaited()


@pytest.mark.asyncio
async def test_zero_signal_still_falls_through_to_the_model():
    """The one case that still pays for a model call: neither rung produced
    any candidate at all, contested or otherwise."""
    with patch(
        "app.ai.workflows.planner.classify_intent_with_model",
        new=AsyncMock(return_value="assist"),
    ) as classify:
        decision = await resolve_plan("Gereğini yap.", "doc-1", llm_client=MagicMock())

    assert decision.source == "model"
    classify.assert_awaited_once()


# ===========================================================================
# _build_clarify_decision (whitebox)
# ===========================================================================
def test_clarify_decision_pairs_a_lone_candidate_with_assist():
    scores = score_intents("Bu taslağı revize et lütfen.", None, has_active_draft=True)
    decision = _build_clarify_decision(scores)

    assert decision.intent == "clarify"
    options = {opt["intent"] for opt in decision.clarification["options"]}
    assert options == {"revise", "assist"}


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
        "Hayır, aslında genel bir soru veya sohbet demek istemiştim.", _PENDING
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
async def test_resolve_plan_checks_pending_clarification_before_the_ladder():
    focus = SessionFocus(pending_clarification=_PENDING)
    classify = AsyncMock(return_value="assist")

    decision = await resolve_plan("evet", None, llm_client=classify, focus=focus)

    assert decision.intent == "draft"
    assert decision.source == "clarification_resolved"
    classify.assert_not_awaited()
