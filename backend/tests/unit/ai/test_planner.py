"""Unit tests for the deterministic intent planner.

The system has four fixed flows and the choice between them is a lookup, not
a reasoning task for the vast majority of messages -- only genuinely
ambiguous ones fall through to a single-label model call.
"""

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


def test_empty_message_resolves_to_chat():
    decision = resolve_plan_deterministic("   ", None)
    assert decision.intent == "chat"
    assert decision.source == "empty"


@pytest.mark.parametrize(
    "message",
    ["Bu evraka cevap yazısı hazırla", "Üst yazı oluştur lütfen", "Dilekçeye cevap yaz"],
)
def test_draft_keywords_resolve_to_the_draft_plan(message):
    decision = resolve_plan_deterministic(message, "uploads/doc.pdf")
    assert decision.intent == "draft"
    assert decision.steps == PLAN_BY_INTENT["draft"]
    assert decision.source == "keyword"


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
    """A bare 'evet' after a chat/document_qa turn has no unambiguous
    follow-up action -- it falls through to the plain short-message default
    instead of silently continuing those flows."""
    decision = resolve_plan_deterministic("evet", None, "chat")
    assert decision.source != "continuation"
    assert decision.source == "short_message"


def test_continuation_does_not_apply_to_long_messages():
    """The 6-word cap keeps this rule from swallowing a genuinely new,
    unrelated request that happens to start with a continuation word."""
    long_message = "tamam ama önce şu diğer konuyu da ele alalım lütfen çünkü acil"
    decision = resolve_plan_deterministic(long_message, None, "draft")
    assert decision is None


def test_continuation_requires_a_continuation_keyword():
    decision = resolve_plan_deterministic("hayır istemiyorum", None, "draft")
    assert decision.source != "continuation"
    assert decision.source == "short_message"


def test_chat_keywords_without_a_document_resolve_to_chat():
    decision = resolve_plan_deterministic("Merhaba, nasılsın?", None)
    assert decision.intent == "chat"


def test_question_with_a_document_resolves_to_document_qa():
    decision = resolve_plan_deterministic("Bu belgede kimin imzası var?", "uploads/doc.pdf")
    assert decision.intent == "document_qa"


def test_a_question_word_without_a_question_mark_still_triggers_document_qa():
    """_looks_like_question also matches on marker words (mi/ne/kim/...), not
    only on a literal '?', so a question phrased without one is still caught."""
    decision = resolve_plan_deterministic("Bu evrak hangi birime ait", "uploads/doc.pdf")
    assert decision.intent == "document_qa"


def test_short_message_without_a_document_resolves_to_chat():
    decision = resolve_plan_deterministic("tamam güzel", None)
    assert decision.intent == "chat"
    assert decision.source == "short_message"


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
    """Never falls back to the full four-step pipeline -- that turns every
    planner hiccup into the slowest possible response."""
    fake_fast_llm.generate_structured_side_effect = [Exception("model unavailable")]

    intent_with_doc = await classify_intent_with_model(fake_fast_llm, "x", "uploads/doc.pdf")
    assert intent_with_doc == "document_qa"

    fake_fast_llm.generate_structured_side_effect = [Exception("model unavailable")]
    intent_without_doc = await classify_intent_with_model(fake_fast_llm, "x", None)
    assert intent_without_doc == "chat"


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

    assert decision.intent == "document_qa"
    assert decision.source == "context_default"
