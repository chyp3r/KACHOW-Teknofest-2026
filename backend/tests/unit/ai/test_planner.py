"""Unit tests for the intent planner's fused decision.

Every signal source used to be pre-summed inside a single per-intent score,
and the top-vs-runner-up *margin* of that sum gated the whole decision. That
made an explicit imperative indistinguishable from a weak structural hint
once both were already folded together: "Cevap yaz." scored `draft=3.0`
against `assist=2.0` (the generic short-message hint), a margin of 1.0 --
just under the old ladder's 1.2 threshold -- and fell through to a
clarifying question a user should never have been asked.

`resolve_plan` now keeps every signal distinct (see
`app.ai.workflows.router_features`) and combines them through a calibrated
model (`app.ai.workflows.router_fusion`, coefficients in
`app.ai.policy.router_weights.ROUTER_WEIGHTS`) into one probability per
intent, then bands on the winner: at or above `tau_high` it commits, between
`tau_high` and `tau_low` a fast-tier model call breaks the tie when one is
available, below `tau_low` it asks the user. Most tests below exercise the
real fitted weights end-to-end (this *is* the router now, not a
swappable implementation detail); the two-pass lexical-then-semantic
orchestration is tested separately with `predict_proba` mocked, since that
is about `resolve_plan`'s control flow, not any particular fit's numbers.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.policy import get_policy
from app.ai.workflows.planner import (
    PLAN_BY_INTENT,
    classify_intent_with_model,
    normalize,
    resolve_plan,
)

_TAU_HIGH = get_policy().intent.tau_high
_TAU_LOW = get_policy().intent.tau_low


def test_normalize_folds_turkish_characters_and_punctuation():
    assert normalize("Çok İyi Bir Öğüt, Şükür!") == "cok iyi bir ogut sukur"


def test_normalize_tolerates_none_and_empty():
    assert normalize("") == ""
    assert normalize(None) == ""


# ===========================================================================
# resolve_plan, real weights: the categories the gold set exists to cover
# ===========================================================================
@pytest.mark.asyncio
async def test_empty_message_resolves_to_assist():
    decision = await resolve_plan("   ", None)
    assert decision.intent == "assist"


@pytest.mark.parametrize(
    "message",
    ["Bu evraka cevap yazısı hazırla", "Üst yazı oluştur lütfen", "Dilekçeye cevap yaz"],
)
@pytest.mark.asyncio
async def test_draft_keywords_resolve_to_the_draft_plan(message):
    decision = await resolve_plan(message, "uploads/doc.pdf")
    assert decision.intent == "draft"
    assert decision.steps == PLAN_BY_INTENT["draft"]


@pytest.mark.asyncio
async def test_analyze_keywords_resolve_to_the_analyze_plan():
    decision = await resolve_plan("Bu evrakı analiz et ve eksik alanları bul", "uploads/x.pdf")
    assert decision.intent == "analyze"
    assert decision.steps == PLAN_BY_INTENT["analyze"]


@pytest.mark.asyncio
async def test_an_unambiguous_short_imperative_resolves_to_draft():
    """The K2 regression: an explicit, unambiguous imperative must not fall
    through to a clarifying question just because it's short and has no
    document attached."""
    for message in ("Cevap yaz.", "Yazı hazırla.", "Kaleme al.", "Tanzim et."):
        decision = await resolve_plan(message, None)
        assert decision.intent == "draft", message
        assert decision.source != "clarify", message


@pytest.mark.parametrize("previous_intent", ["draft", "analyze"])
@pytest.mark.asyncio
async def test_short_affirmative_continues_the_previous_continuable_intent(previous_intent):
    decision = await resolve_plan("evet, hazırla", None, previous_intent=previous_intent)
    assert decision.intent == previous_intent
    assert decision.steps == PLAN_BY_INTENT[previous_intent]


@pytest.mark.asyncio
async def test_continuation_does_not_apply_to_non_continuable_previous_intents():
    """A bare 'evet' after an assist turn has no unambiguous follow-up
    action -- it resolves on its own (short-message) merits instead of
    silently continuing that flow."""
    decision = await resolve_plan("evet", None, previous_intent="assist")
    assert decision.intent == "assist"


@pytest.mark.asyncio
async def test_a_question_with_a_document_resolves_to_assist():
    decision = await resolve_plan("Bu belgede kimin imzası var?", "uploads/doc.pdf")
    assert decision.intent == "assist"


@pytest.mark.parametrize(
    "message",
    [
        "Az önce sana ne sormuştum?",
        "Bu konuşmada daha önce ne konuştuk?",
        "Hatırlıyor musun, ilk mesajımda ne sordum?",
    ],
)
@pytest.mark.asyncio
async def test_memory_recall_question_resolves_to_assist_even_with_a_document(message):
    decision = await resolve_plan(message, "uploads/doc.pdf")
    assert decision.intent == "assist"


@pytest.mark.asyncio
async def test_memory_recall_does_not_override_draft_keyword_precedence():
    decision = await resolve_plan(
        "Az önce taslak hazırlamanı istemiştim, şimdi hazırla", "uploads/doc.pdf"
    )
    assert decision.intent == "draft"


# --- The categories the pre-scoring cascade could not reach ------------------
#
# `evaluation/reports/all-baseline.md` measured the ordered cascade at 0.00 on
# `inversion` and `precedence` -- not "weak", zero, every case. These pin the
# behaviour that replaced it.


@pytest.mark.asyncio
async def test_a_question_about_drafting_does_not_start_a_drafting_run():
    """The `inversion` failure: "resmi yazi" matched before anything else could
    object, so a definition question ran classification -> draft -> routing."""
    decision = await resolve_plan("Resmi yazı ne demek, kısaca anlatır mısın?", None)
    assert decision.intent == "assist"
    assert decision.steps == PLAN_BY_INTENT["assist"]


@pytest.mark.asyncio
async def test_a_greeting_still_resolves_when_a_document_is_attached():
    """The `precedence` failure: the greeting branch was gated on
    `document_id is None`, so this fell through every branch and escalated."""
    decision = await resolve_plan("Merhaba", "uploads/doc.pdf")
    assert decision.intent == "assist"


@pytest.mark.asyncio
async def test_a_farewell_after_a_draft_turn_does_not_produce_a_draft():
    decision = await resolve_plan(
        "İyi akşamlar, yarın devam ederiz.", "uploads/doc.pdf", previous_intent="draft"
    )
    assert decision.intent == "assist"


@pytest.mark.asyncio
async def test_a_compound_request_runs_one_pipeline_covering_both_readings():
    decision = await resolve_plan(
        "Uygunluk denetimi yap, sonra cevabı kaleme al.", "uploads/doc.pdf"
    )
    assert decision.source == "compound"
    assert decision.intent == "draft"
    assert decision.steps == ["classification", "draft", "routing"]


@pytest.mark.asyncio
async def test_compound_merging_keeps_canonical_step_order():
    decision = await resolve_plan(
        "Belgeyi kontrol et ve gerekiyorsa bir üst yazı çıkar.", "uploads/doc.pdf"
    )
    assert decision.steps == ["classification", "draft", "routing"]


@pytest.mark.asyncio
async def test_only_draft_and_analyze_compose_into_one_plan():
    """Merging `assist` into `draft` would answer conversationally *and* start
    a drafting run, which is not what either reading asked for."""
    decision = await resolve_plan("Merhaba", "uploads/doc.pdf")
    assert decision.source != "compound"
    assert decision.steps == PLAN_BY_INTENT["assist"]


@pytest.mark.asyncio
async def test_every_decision_carries_its_confidence_and_evidence():
    decision = await resolve_plan("Bu evraka bir cevap yazısı hazırla.", "uploads/doc.pdf")
    assert 0.0 <= decision.confidence <= 1.0
    assert decision.evidence
    assert "draft.explicit_request" in decision.evidence
    assert isinstance(decision.alternatives, tuple)


# ===========================================================================
# The model band and the ask-instead floor
# ===========================================================================
@pytest.mark.asyncio
async def test_resolve_plan_skips_the_model_when_fusion_already_commits(fake_fast_llm):
    decision = await resolve_plan("taslak hazırla", "uploads/doc.pdf", fake_fast_llm)
    assert decision.intent == "draft"
    assert fake_fast_llm.generate_structured_calls == []


@pytest.mark.asyncio
async def test_a_genuinely_underspecified_command_asks_without_a_client():
    decision = await resolve_plan("Gereğini yap.", "uploads/doc.pdf", llm_client=None)
    assert decision.source == "clarify"


@pytest.mark.asyncio
async def test_a_genuinely_underspecified_command_does_not_pay_for_a_model_call_either():
    """Below `tau_low` there is too little signal for a model call to be
    worth its round trip -- the ladder asks the user even when a client is
    available, rather than escalating everything it cannot resolve on its
    own the way the pre-fusion ladder's `context_default` branch used to."""
    classify = AsyncMock(return_value="assist")
    with patch("app.ai.workflows.planner.classify_intent_with_model", new=classify):
        decision = await resolve_plan("Gereğini yap.", "uploads/doc.pdf", llm_client=MagicMock())

    assert decision.source == "clarify"
    classify.assert_not_awaited()


# ===========================================================================
# Model fallback (classify_intent_with_model itself)
# ===========================================================================
@pytest.mark.asyncio
async def test_classify_intent_with_model_returns_the_structured_label(fake_fast_llm):
    from app.ai.workflows.planner import IntentOutput

    fake_fast_llm.generate_structured_return = IntentOutput(intent="draft")
    intent = await classify_intent_with_model(fake_fast_llm, "belirsiz bir mesaj", None)
    assert intent == "draft"


@pytest.mark.asyncio
async def test_classify_intent_with_model_degrades_safely_on_failure(fake_fast_llm):
    fake_fast_llm.generate_structured_side_effect = [Exception("model unavailable")]
    intent = await classify_intent_with_model(fake_fast_llm, "x", "uploads/doc.pdf")
    assert intent == "assist"


# ===========================================================================
# The two-pass lexical-then-semantic orchestration
#
# Mocked at `predict_proba` rather than exercised with real messages: what's
# under test here is *when* resolve_plan pays for a second (semantic) fusion
# pass, not what any particular fit's numbers happen to produce.
# ===========================================================================
class _StubMatcher:
    def __init__(self, result):
        self._result = result
        self.calls = []

    async def label_similarities(self, text, family):
        self.calls.append((text, family))
        return self._result


def _confident(intent: str) -> dict[str, float]:
    remainder = (1.0 - (_TAU_HIGH + 0.1)) / 3
    probs = {name: remainder for name in ("draft", "analyze", "assist", "revise")}
    probs[intent] = _TAU_HIGH + 0.1
    return probs


def _contested() -> dict[str, float]:
    """Top probability strictly between tau_low and tau_high -- the model band."""
    top = (_TAU_LOW + _TAU_HIGH) / 2
    remainder = (1.0 - top) / 3
    probs = {name: remainder for name in ("draft", "analyze", "assist", "revise")}
    probs["draft"] = top
    return probs


@pytest.mark.asyncio
async def test_the_semantic_layer_is_skipped_when_lexical_fusion_already_commits():
    """The fast path must stay free: a message the lexical evidence alone
    already resolves must never pay for an embedding call."""
    matcher = _StubMatcher({"draft": 0.9})

    with patch("app.ai.workflows.planner.predict_proba", return_value=_confident("draft")):
        decision = await resolve_plan("Bu evraka bir cevap yazısı hazırla.", "uploads/doc.pdf", matcher=matcher)

    assert decision.intent == "draft"
    assert decision.source == "fused"
    assert matcher.calls == []


@pytest.mark.asyncio
async def test_semantic_evidence_can_push_a_contested_case_over_tau_high():
    """A message the lexical-only pass leaves contested can still resolve
    outright once semantic evidence is folded in -- a second, decisive fusion
    pass, not a separate rung deciding alone."""
    matcher = _StubMatcher({"analyze": 0.85})

    with patch(
        "app.ai.workflows.planner.predict_proba",
        side_effect=[_contested(), _confident("analyze")],
    ):
        decision = await resolve_plan("belirsiz bir mesaj", "uploads/doc.pdf", matcher=matcher)

    assert decision.intent == "analyze"
    assert decision.source == "fused_semantic"
    assert matcher.calls == [("belirsiz bir mesaj", "intent")]


@pytest.mark.asyncio
async def test_an_empty_semantic_result_does_not_trigger_a_second_fusion_pass():
    """A matcher that is consulted but has nothing to say (embeddings outage,
    unavailable family) must not fabricate a second pass -- the message stays
    exactly as contested as the lexical-only pass found it."""
    matcher = _StubMatcher(None)
    classify = AsyncMock(return_value="assist")

    with patch(
        "app.ai.workflows.planner.predict_proba", return_value=_contested()
    ) as predict, patch("app.ai.workflows.planner.classify_intent_with_model", new=classify):
        decision = await resolve_plan(
            "belirsiz bir mesaj", "uploads/doc.pdf", llm_client=MagicMock(), matcher=matcher
        )

    assert predict.call_count == 1
    assert decision.source == "model"


@pytest.mark.asyncio
async def test_no_matcher_and_an_unavailable_matcher_behave_identically():
    classify = AsyncMock(return_value="assist")
    with patch(
        "app.ai.workflows.planner.predict_proba", return_value=_contested()
    ), patch("app.ai.workflows.planner.classify_intent_with_model", new=classify):
        without_matcher = await resolve_plan(
            "belirsiz bir mesaj", "uploads/doc.pdf", llm_client=MagicMock()
        )
        with_empty_matcher = await resolve_plan(
            "belirsiz bir mesaj",
            "uploads/doc.pdf",
            llm_client=MagicMock(),
            matcher=_StubMatcher(None),
        )

    assert without_matcher.source == with_empty_matcher.source == "model"
