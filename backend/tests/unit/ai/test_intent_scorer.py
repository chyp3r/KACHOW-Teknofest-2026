"""Guards the scoring mechanics that make the old cascade's failures fixable.

The cascade this replaced returned on the first keyword hit, which made table
order the decision. Three properties fix that, and each is easy to lose to a
well-meaning simplification:

* **Evidence accumulates.** Two intents in one message must both score, so the
  margin between them stays visible instead of one short-circuiting the other.
* **Counter-signals invalidate, they do not merely outweigh.** A definitional
  question and a memory-recall question each remove evidence that is not
  applicable, rather than piling weight on the other side. Turning either into
  a plain weight reintroduces a failure the repo already fixed once.
* **Order inside the scorer matters.** The memory-recall counter runs after
  every document_qa signal has accumulated; moving it earlier silently stops it
  cancelling the question hint.
"""

import pytest

from app.ai.workflows.intent_scorer import (
    COMPOUND_FLOOR,
    DECISIVE_MARGIN,
    PRESENCE_FLOOR,
    normalize,
    score_intents,
)

DOCUMENT = "uploads/evrak.pdf"


def test_normalize_folds_turkish_characters_and_punctuation():
    assert normalize("Çok İyi Bir Öğüt, Şükür!") == "cok iyi bir ogut sukur"
    assert normalize(None) == ""


def test_an_empty_message_scores_chat_decisively():
    scores = score_intents("   ", None)

    assert scores.ranked[0][0] == "chat"
    assert "chat.empty_message" in scores.evidence


def test_evidence_accumulates_instead_of_short_circuiting():
    """Both readings of a compound request must be visible in the scores."""
    scores = score_intents("Belgeyi incele ve cevap yazısı oluştur.", DOCUMENT)

    assert scores.scores["analyze"] >= COMPOUND_FLOOR
    assert scores.scores["draft"] >= COMPOUND_FLOOR


def test_a_definitional_question_cancels_the_domain_noun_it_contains():
    """"Üst yazı ne demek?" mentions drafting; it does not request it."""
    scores = score_intents("Üst yazı ne demek?", None)

    assert scores.ranked[0][0] == "chat"
    assert "draft.definitional_counter" in scores.evidence
    assert scores.scores.get("draft", 0.0) < PRESENCE_FLOOR


def test_a_definitional_counter_outweighs_an_explicit_phrase_plus_a_noun():
    """"taslak olustur" is a substring of "taslak oluşturma"; the counter has to
    be sized for that coincidence, not just for the noun alone."""
    scores = score_intents("Taslak oluşturma süreci sistemde nasıl işliyor?", None)

    assert scores.ranked[0][0] == "chat"
    assert scores.margin >= DECISIVE_MARGIN


def test_memory_recall_invalidates_document_evidence_rather_than_outweighing_it():
    scores = score_intents("Bu belgede kaç madde vardı, hatırlıyor musun?", DOCUMENT)

    assert "document_qa.memory_recall_counter" in scores.evidence
    assert scores.ranked[0][0] == "chat"


def test_an_explicit_drafting_request_still_beats_memory_recall():
    """The counter must not be a blanket "recall always wins" rule."""
    scores = score_intents(
        "Az önce taslak hazırlamanı istemiştim, şimdi hazırla", DOCUMENT
    )

    assert scores.ranked[0][0] == "draft"


def test_a_greeting_resolves_the_same_way_with_and_without_a_document():
    """Document state is a weight here, never a gate -- gating the greeting rule
    on `document_id is None` is what made "Merhaba" with an attachment
    unresolvable."""
    without = score_intents("Merhaba", None)
    with_document = score_intents("Merhaba", DOCUMENT)

    assert without.ranked[0][0] == "chat"
    assert with_document.ranked[0][0] == "chat"


def test_a_farewell_is_not_read_as_consent_to_continue():
    """"İyi akşamlar, yarın devam ederiz" contains "devam" and means the
    opposite of continuing now."""
    scores = score_intents("İyi akşamlar, yarın devam ederiz.", DOCUMENT, "draft")

    assert "draft.continuation" not in scores.evidence
    assert scores.ranked[0][0] == "chat"


def test_a_short_affirmative_does_not_double_count_its_own_brevity():
    """Continuation and the short-message hint are the same evidence twice;
    firing both left the two scores too close to decide."""
    scores = score_intents("evet, hazırla", None, "draft")

    assert "draft.continuation" in scores.evidence
    assert "chat.short_message" not in scores.evidence
    assert scores.margin >= DECISIVE_MARGIN


def test_continuation_is_bounded_by_message_length():
    scores = score_intents(
        "tamam ama önce şu diğer konuyu da ele alalım lütfen çünkü acil", None, "draft"
    )

    assert "draft.continuation" not in scores.evidence


@pytest.mark.parametrize("previous_intent", ["chat", "document_qa", None])
def test_continuation_only_applies_to_continuable_previous_intents(previous_intent):
    scores = score_intents("evet", None, previous_intent)

    assert not [item for item in scores.evidence if item.endswith(".continuation")]


def test_confidence_tracks_the_margin_and_stays_bounded():
    confident = score_intents("Bu evraka bir cevap yazısı hazırla.", DOCUMENT)
    contested = score_intents("Bunu hallet.", DOCUMENT)

    assert 0.0 <= confident.confidence <= 1.0
    assert 0.0 <= contested.confidence <= 1.0
    assert confident.confidence > contested.confidence


def test_ranked_breaks_ties_deterministically():
    """Two runs of the same message must not disagree about the runner-up."""
    message = "Belgeyi incele ve cevap yazısı oluştur."

    assert score_intents(message, DOCUMENT).ranked == score_intents(message, DOCUMENT).ranked


def test_every_decision_reports_the_rules_that_produced_it():
    scores = score_intents("Bu evraka bir cevap yazısı hazırla.", DOCUMENT)

    assert scores.evidence
    assert all(isinstance(rule_id, str) and "." in rule_id for rule_id in scores.evidence)


def test_a_request_softener_does_not_win_document_qa_on_its_own():
    """"Bunun cevabını sen yazar mısın?" carries no document phrase; the
    question mark alone used to be enough for `document_qa` to clear both the
    presence floor and the decisive margin unopposed. A politely-phrased
    request is not a content lookup, so this must abstain, not answer wrong."""
    scores = score_intents("Bunun cevabını sen yazar mısın?", DOCUMENT)

    assert "document_qa.request_softener_counter" in scores.evidence
    assert scores.scores.get("document_qa", 0.0) < PRESENCE_FLOOR


def test_a_request_softener_does_not_override_a_real_content_question():
    """The softener counter is gated on the absence of `about_the_document`:
    unlike memory recall, a softener is only a grammatical mood, and "Bu
    belgede ne yazdığını söyler misin?" is still a genuine document question."""
    scores = score_intents("Bu belgede ne yazdığını söyler misin?", DOCUMENT)

    assert "document_qa.request_softener_counter" not in scores.evidence
    assert scores.ranked[0][0] == "document_qa"


def test_a_definitional_softener_does_not_capture_a_document_specific_question():
    """"anlatır mısın" no longer sits in the definitional-question surfaces on
    its own: asking to explain a specific document's status is not a question
    about a general concept, even though it uses the same softener."""
    scores = score_intents("Şu belgeye bir göz atıp durumu anlatır mısın?", DOCUMENT)

    assert "chat.definitional_question" not in scores.evidence


def test_a_genuine_definitional_question_still_resolves_to_chat():
    """The removed bare softener phrases were redundant for every existing
    case: "ne demek" alone still carries the inversion category."""
    scores = score_intents("Resmi yazı ne demek, kısaca anlatır mısın?", None)

    assert scores.ranked[0][0] == "chat"
    assert "draft.definitional_counter" in scores.evidence


def test_a_compliance_question_is_evidence_for_analyze():
    """"kurallara uyup uymadığını" is the same compliance concept as the
    existing "mevzuata uygun" surface, just a different conjugation."""
    scores = score_intents("Bu yazının kurallara uyup uymadığını söyler misin?", DOCUMENT)

    assert scores.scores.get("analyze", 0.0) >= PRESENCE_FLOOR


def test_evvelki_is_recognised_as_a_memory_recall_synonym():
    """"evvelki" is a synonym of the already-covered "önceki"; a document
    attached must not turn a question about the conversation into one about
    the document's contents."""
    scores = score_intents("Bir evvelki turda bana ne iletmiştin?", DOCUMENT)

    assert "chat.memory_recall" in scores.evidence
    assert scores.ranked[0][0] == "chat"
