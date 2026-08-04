"""Unit tests for the deterministic intent planner.

The choice between the system's three flows is scored, not looked up: a message
is weighed against a declarative evidence table and the decision is the margin
between the top two intents. Only genuinely balanced or evidence-free messages
fall through to a single-label model call.

The `source` assertions below describe the *mechanism* that decided, and its
vocabulary changed with the rewrite -- "keyword"/"short_message"/"memory_recall"
named branches of an ordered cascade that no longer exists. What has not
changed, and is what these tests actually guard, is the resolved intent and its
step list for every case the cascade got right.

`chat` and `document_qa` are one intent here, `assist`: the router used to have
to decide in advance whether a message needed retrieval, which is exactly the
decision a chunk of `intent_rules.py`/`intent_scorer.py` existed to arbitrate.
The assistant agent now makes that call itself, per-turn, via a tool loop -- so
every case below that used to split on "does this need the document" resolves
to the same intent regardless.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.workflows.planner import (
    PLAN_BY_INTENT,
    classify_intent_with_model,
    normalize,
    resolve_plan,
    resolve_plan_deterministic,
)


def test_normalize_folds_turkish_characters_and_punctuation():
    assert normalize("Çok İyi Bir Öğüt, Şükür!") == "cok iyi bir ogut sukur"


def test_normalize_tolerates_none_and_empty():
    assert normalize("") == ""
    assert normalize(None) == ""


def test_empty_message_resolves_to_assist():
    decision = resolve_plan_deterministic("   ", None)
    assert decision.intent == "assist"
    assert decision.source == "empty"


@pytest.mark.parametrize(
    "message",
    ["Bu evraka cevap yazısı hazırla", "Üst yazı oluştur lütfen", "Dilekçeye cevap yaz"],
)
def test_draft_keywords_resolve_to_the_draft_plan(message):
    decision = resolve_plan_deterministic(message, "uploads/doc.pdf")
    assert decision.intent == "draft"
    assert decision.steps == PLAN_BY_INTENT["draft"]
    assert decision.source == "scored"


def test_analyze_keywords_resolve_to_the_analyze_plan():
    decision = resolve_plan_deterministic("Bu evrakı analiz et ve eksik alanları bul", "uploads/x.pdf")
    assert decision.intent == "analyze"
    assert decision.steps == PLAN_BY_INTENT["analyze"]


def test_draft_keyword_wins_over_analyze_keyword_when_both_present():
    """'bu belgeyi incele ve cevap yazısı hazırla' is both a document
    reference and a drafting request -- drafting is the superset flow, so it
    must take precedence."""
    decision = resolve_plan_deterministic("Belgeyi incele ve cevap yazısı hazırla", "uploads/x.pdf")
    assert decision.intent == "draft"


@pytest.mark.parametrize("previous_intent", ["draft", "analyze"])
def test_short_affirmative_continues_the_previous_continuable_intent(previous_intent):
    decision = resolve_plan_deterministic("evet, hazırla", None, previous_intent)
    assert decision.intent == previous_intent
    assert decision.steps == PLAN_BY_INTENT[previous_intent]
    assert decision.source == "continuation"
    assert "devamı" in decision.reasoning


def test_continuation_does_not_apply_to_non_continuable_previous_intents():
    """A bare 'evet' after an assist turn has no unambiguous follow-up
    action -- it falls through to the plain short-message default instead of
    silently continuing that flow."""
    decision = resolve_plan_deterministic("evet", None, "assist")
    assert decision.source != "continuation"
    assert decision.source == "scored"


def test_continuation_does_not_apply_to_long_messages():
    """The 6-word cap keeps this rule from swallowing a genuinely new,
    unrelated request that happens to start with a continuation word."""
    long_message = "tamam ama önce şu diğer konuyu da ele alalım lütfen çünkü acil"
    decision = resolve_plan_deterministic(long_message, None, "draft")
    assert decision is None


def test_continuation_requires_a_continuation_keyword():
    decision = resolve_plan_deterministic("hayır istemiyorum", None, "draft")
    assert decision.source != "continuation"
    assert decision.source == "scored"


def test_chat_keywords_without_a_document_resolve_to_assist():
    decision = resolve_plan_deterministic("Merhaba, nasılsın?", None)
    assert decision.intent == "assist"


def test_question_with_a_document_resolves_to_assist():
    decision = resolve_plan_deterministic("Bu belgede kimin imzası var?", "uploads/doc.pdf")
    assert decision.intent == "assist"


def test_a_question_word_without_a_question_mark_still_triggers_assist():
    """_looks_like_question also matches on marker words (mi/ne/kim/...), not
    only on a literal '?', so a question phrased without one is still caught."""
    decision = resolve_plan_deterministic("Bu evrak hangi birime ait", "uploads/doc.pdf")
    assert decision.intent == "assist"


@pytest.mark.parametrize(
    "message",
    [
        "Az önce sana ne sormuştum?",
        "Biraz önce ne demiştim?",
        "Bu konuşmada daha önce ne konuştuk?",
        "Hatırlıyor musun, ilk mesajımda ne sordum?",
        "Sana daha önce ne demiştim?",
    ],
)
def test_memory_recall_question_resolves_to_assist_even_with_a_document(message):
    decision = resolve_plan_deterministic(message, "uploads/doc.pdf")
    assert decision.intent == "assist"
    assert decision.source == "scored"


def test_memory_recall_question_resolves_to_assist_without_a_document():
    decision = resolve_plan_deterministic(
        "Bu konuşmada daha önce hangi konuyu konuştuk, hatırlıyor musun?", None
    )
    assert decision.intent == "assist"
    assert decision.source == "scored"


def test_memory_recall_wins_even_when_the_message_also_looks_like_a_document_question():
    """A message that is both document-shaped ('bu belgede...') and
    memory-shaped ('hatırlıyor musun') still resolves to assist -- before the
    chat/document_qa merge both readings had to be reconciled onto the same
    intent by a dedicated counter-signal; now they simply accumulate."""
    decision = resolve_plan_deterministic(
        "Bu belgede kaç madde vardı, hatırlıyor musun?", "uploads/doc.pdf"
    )
    assert decision.intent == "assist"


def test_memory_recall_does_not_override_draft_keyword_precedence():
    decision = resolve_plan_deterministic(
        "Az önce taslak hazırlamanı istemiştim, şimdi hazırla", "uploads/doc.pdf"
    )
    assert decision.intent == "draft"


def test_short_message_without_a_document_resolves_to_assist():
    decision = resolve_plan_deterministic("tamam güzel", None)
    assert decision.intent == "assist"
    assert decision.source == "scored"


def test_ambiguous_message_returns_none():
    """A message that is long, has a document but doesn't look like a
    question, and matches no keyword list must fall through to the model."""
    decision = resolve_plan_deterministic(
        "Bu konuda geçen hafta da benzer bir durum yaşanmıştı ve tekrar ele almak istiyorum",
        "uploads/doc.pdf",
    )
    assert decision is None


# ==========================================
# Model fallback (only reached for ambiguous messages)
# ==========================================
@pytest.mark.asyncio
async def test_classify_intent_with_model_returns_the_structured_label(fake_fast_llm):
    from app.ai.workflows.planner import IntentOutput

    fake_fast_llm.generate_structured_return = IntentOutput(intent="draft")

    intent = await classify_intent_with_model(fake_fast_llm, "belirsiz bir mesaj", None)

    assert intent == "draft"


@pytest.mark.asyncio
async def test_classify_intent_with_model_degrades_safely_on_failure(fake_fast_llm):
    """Never falls back to the full three-step drafting pipeline -- that turns
    every planner hiccup into the slowest possible response. Document or not,
    the cheapest flow that can still answer is the same one now: assist reaches
    for retrieval itself when it needs to."""
    fake_fast_llm.generate_structured_side_effect = [Exception("model unavailable")]

    intent_with_doc = await classify_intent_with_model(fake_fast_llm, "x", "uploads/doc.pdf")
    assert intent_with_doc == "assist"

    fake_fast_llm.generate_structured_side_effect = [Exception("model unavailable")]
    intent_without_doc = await classify_intent_with_model(fake_fast_llm, "x", None)
    assert intent_without_doc == "assist"


@pytest.mark.asyncio
async def test_resolve_plan_skips_the_model_when_deterministic_resolution_succeeds(fake_fast_llm):
    decision = await resolve_plan("taslak hazırla", "uploads/doc.pdf", fake_fast_llm)

    assert decision.intent == "draft"
    assert fake_fast_llm.generate_structured_calls == []


@pytest.mark.asyncio
async def test_resolve_plan_without_a_client_uses_the_context_default_for_ambiguous_messages():
    decision = await resolve_plan(
        "Bu konuda geçen hafta da benzer bir durum yaşanmıştı ve tekrar ele almak istiyorum",
        "uploads/doc.pdf",
        llm_client=None,
    )

    assert decision.intent == "assist"
    assert decision.source == "context_default"


# --- Scored resolution: the categories the cascade could not reach -----------
#
# `evaluation/reports/all-baseline.md` measured the ordered cascade at 0.00 on
# `inversion` and `precedence` -- not "weak", zero, every case. These pin the
# behaviour that replaced it, and the plan-shape guarantees that come with it.


def test_a_question_about_drafting_does_not_start_a_drafting_run():
    """The `inversion` failure: "resmi yazi" matched before anything else could
    object, so a definition question ran classification -> draft -> routing."""
    decision = resolve_plan_deterministic("Resmi yazı ne demek, kısaca anlatır mısın?", None)

    assert decision.intent == "assist"
    assert decision.steps == PLAN_BY_INTENT["assist"]


def test_a_greeting_still_resolves_when_a_document_is_attached():
    """The `precedence` failure: the greeting branch was gated on
    `document_id is None`, so this fell through every branch and escalated."""
    decision = resolve_plan_deterministic("Merhaba", "uploads/doc.pdf")

    assert decision.intent == "assist"


def test_a_farewell_after_a_draft_turn_does_not_produce_a_draft():
    decision = resolve_plan_deterministic(
        "İyi akşamlar, yarın devam ederiz.", "uploads/doc.pdf", "draft"
    )

    assert decision.intent == "assist"


def test_a_compound_request_runs_one_pipeline_covering_both_readings():
    decision = resolve_plan_deterministic(
        "Uygunluk denetimi yap, sonra cevabı kaleme al.", "uploads/doc.pdf"
    )

    assert decision.source == "compound"
    assert decision.intent == "draft"
    assert decision.steps == ["classification", "draft", "routing"]


def test_compound_merging_keeps_canonical_step_order():
    """The merge must not invent an ordering -- routing after draft after
    classification, whichever intent contributed which step."""
    decision = resolve_plan_deterministic(
        "Belgeyi kontrol et ve gerekiyorsa bir üst yazı çıkar.", "uploads/doc.pdf"
    )

    assert decision.steps == ["classification", "draft", "routing"]


def test_only_draft_and_analyze_compose_into_one_plan():
    """Merging `assist` into `draft` would answer conversationally *and* start
    a drafting run, which is not what either reading asked for."""
    decision = resolve_plan_deterministic("Merhaba", "uploads/doc.pdf")

    assert decision.source != "compound"
    assert decision.steps == PLAN_BY_INTENT["assist"]


def test_an_underspecified_command_escalates_rather_than_guessing():
    decision = resolve_plan_deterministic("Gereğini yap.", "uploads/doc.pdf")

    assert decision is None


def test_every_decision_carries_its_confidence_and_evidence():
    """The cascade reported only which branch it took. A production decision
    now has to be explainable after the fact."""
    decision = resolve_plan_deterministic("Bu evraka bir cevap yazısı hazırla.", "uploads/doc.pdf")

    assert 0.0 <= decision.confidence <= 1.0
    assert decision.evidence
    assert "draft.explicit_request" in decision.evidence
    assert isinstance(decision.alternatives, tuple)


# --- The escalation ladder ---------------------------------------------------
#
# Three rungs, cheapest first: lexical rules (~0ms), semantic prototypes
# (~50-150ms), fast-tier model (~1-3s). What matters structurally is that each
# rung only sees what the one below it declined, and that a non-decisive
# semantic match falls through rather than being acted on.


class _StubMatch:
    def __init__(self, label, decisive, similarity=0.9, gap=0.2):
        self.label = label
        self.decisive = decisive
        self.similarity = similarity
        self.runner_up_gap = gap


class _StubMatcher:
    def __init__(self, result):
        self._result = result
        self.calls = []

    async def match(self, text, family):
        self.calls.append((text, family))
        return self._result


@pytest.mark.asyncio
async def test_the_semantic_rung_is_skipped_when_the_lexical_layer_decides():
    """The fast path must stay free: a message the rules resolve never pays for
    an embedding."""
    matcher = _StubMatcher(_StubMatch("assist", decisive=True))

    decision = await resolve_plan(
        "Bu evraka bir cevap yazısı hazırla.", "uploads/doc.pdf", matcher=matcher
    )

    assert decision.intent == "draft"
    assert decision.source != "semantic"
    assert matcher.calls == []


@pytest.mark.asyncio
async def test_a_decisive_semantic_match_resolves_without_a_model_call():
    matcher = _StubMatcher(_StubMatch("draft", decisive=True))
    llm = MagicMock()

    decision = await resolve_plan(
        "Gereğini yap.", "uploads/doc.pdf", llm_client=llm, matcher=matcher
    )

    assert decision.intent == "draft"
    assert decision.source == "semantic"
    assert decision.evidence == ("semantic.draft",)
    assert matcher.calls == [("Gereğini yap.", "intent")]
    llm.assert_not_called()


@pytest.mark.asyncio
async def test_a_non_decisive_semantic_match_falls_through_to_the_model():
    """Having a favourite is not the same as having an answer."""
    matcher = _StubMatcher(_StubMatch("draft", decisive=False))

    with patch(
        "app.ai.workflows.planner.classify_intent_with_model",
        new=AsyncMock(return_value="assist"),
    ) as classify:
        decision = await resolve_plan(
            "Gereğini yap.", "uploads/doc.pdf", llm_client=MagicMock(), matcher=matcher
        )

    assert decision.source == "model"
    assert decision.intent == "assist"
    classify.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_unavailable_matcher_leaves_the_ladder_as_it_was():
    """No matcher configured, or one that returns nothing, must behave exactly
    like the two-rung ladder that existed before this layer."""
    with patch(
        "app.ai.workflows.planner.classify_intent_with_model",
        new=AsyncMock(return_value="assist"),
    ):
        without = await resolve_plan(
            "Gereğini yap.", "uploads/doc.pdf", llm_client=MagicMock()
        )
        with_empty = await resolve_plan(
            "Gereğini yap.",
            "uploads/doc.pdf",
            llm_client=MagicMock(),
            matcher=_StubMatcher(None),
        )

    assert without.source == with_empty.source == "model"


@pytest.mark.asyncio
async def test_a_semantic_label_outside_the_known_intents_is_ignored():
    """The vector file is data on disk; a label that is not a plan must not be
    turned into one."""
    matcher = _StubMatcher(_StubMatch("bilinmeyen", decisive=True))

    with patch(
        "app.ai.workflows.planner.classify_intent_with_model",
        new=AsyncMock(return_value="assist"),
    ):
        decision = await resolve_plan(
            "Gereğini yap.", "uploads/doc.pdf", llm_client=MagicMock(), matcher=matcher
        )

    assert decision.source == "model"
