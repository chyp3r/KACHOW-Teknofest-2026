"""Guards the scoring mechanics that make the old cascade's failures fixable.

The cascade this replaced returned on the first keyword hit, which made table
order the decision. Two properties fix that, and each is easy to lose to a
well-meaning simplification:

* **Evidence accumulates.** Two intents in one message must both score, so the
  margin between them stays visible instead of one short-circuiting the other.
* **A counter-signal invalidates, it does not merely outweigh.** A definitional
  question removes evidence that is not applicable (the domain noun it
  contains), rather than piling weight on the other side. Turning it into a
  plain weight reintroduces a failure the repo already fixed once.

`chat` and `document_qa` used to be two separate intents here, each with its
own score bucket, and two of the counter-signals below (a memory-recall
question, a politely-phrased request) existed only to arbitrate which of the
two a message should win. Both are now the same `assist` bucket, so evidence
for either reading simply accumulates instead of competing -- see the tests
each counter's removal replaced.
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


def test_an_empty_message_scores_assist_decisively():
    scores = score_intents("   ", None)

    assert scores.ranked[0][0] == "assist"
    assert "assist.empty_message" in scores.evidence


def test_evidence_accumulates_instead_of_short_circuiting():
    """Both readings of a compound request must be visible in the scores."""
    scores = score_intents("Belgeyi incele ve cevap yazısı oluştur.", DOCUMENT)

    assert scores.scores["analyze"] >= COMPOUND_FLOOR
    assert scores.scores["draft"] >= COMPOUND_FLOOR


def test_a_definitional_question_cancels_the_domain_noun_it_contains():
    """"Üst yazı ne demek?" mentions drafting; it does not request it."""
    scores = score_intents("Üst yazı ne demek?", None)

    assert scores.ranked[0][0] == "assist"
    assert "draft.definitional_counter" in scores.evidence
    assert scores.scores.get("draft", 0.0) < PRESENCE_FLOOR


def test_a_definitional_counter_outweighs_an_explicit_phrase_plus_a_noun():
    """"taslak olustur" is a substring of "taslak oluşturma"; the counter has to
    be sized for that coincidence, not just for the noun alone."""
    scores = score_intents("Taslak oluşturma süreci sistemde nasıl işliyor?", None)

    assert scores.ranked[0][0] == "assist"
    assert scores.margin >= DECISIVE_MARGIN


def test_memory_recall_and_document_evidence_both_accumulate_into_assist():
    """Before the `chat`/`document_qa` merge, a memory-recall question had to
    *invalidate* the document-question evidence it also carried, or the two
    competing buckets could pick the wrong one. Now both readings feed the
    same `assist` bucket, so they simply add up -- no invalidation needed."""
    scores = score_intents("Bu belgede kaç madde vardı, hatırlıyor musun?", DOCUMENT)

    assert "assist.memory_recall" in scores.evidence
    assert "assist.about_the_document" in scores.evidence
    assert scores.ranked[0][0] == "assist"


def test_an_explicit_drafting_request_still_beats_memory_recall():
    """A recall phrase is not a blanket "recall always wins" rule -- an
    explicit drafting request in the same message must still win outright."""
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

    assert without.ranked[0][0] == "assist"
    assert with_document.ranked[0][0] == "assist"


def test_a_farewell_is_not_read_as_consent_to_continue():
    """"İyi akşamlar, yarın devam ederiz" contains "devam" and means the
    opposite of continuing now."""
    scores = score_intents("İyi akşamlar, yarın devam ederiz.", DOCUMENT, "draft")

    assert "draft.continuation" not in scores.evidence
    assert scores.ranked[0][0] == "assist"


def test_a_short_affirmative_does_not_double_count_its_own_brevity():
    """Continuation and the short-message hint are the same evidence twice;
    firing both left the two scores too close to decide."""
    scores = score_intents("evet, hazırla", None, "draft")

    assert "draft.continuation" in scores.evidence
    assert "assist.short_message" not in scores.evidence
    assert scores.margin >= DECISIVE_MARGIN


def test_continuation_is_bounded_by_message_length():
    scores = score_intents(
        "tamam ama önce şu diğer konuyu da ele alalım lütfen çünkü acil", None, "draft"
    )

    assert "draft.continuation" not in scores.evidence


@pytest.mark.parametrize("previous_intent", ["assist", None])
def test_continuation_only_applies_to_continuable_previous_intents(previous_intent):
    scores = score_intents("evet", None, previous_intent)

    assert not [item for item in scores.evidence if item.endswith(".continuation")]


def test_a_targeted_revise_instruction_is_not_read_as_draft_continuation():
    """The router-level cause of a live bug report: "Kapanışı 'X' yap." right
    after a draft turn is five words and ends in "yap" (a CONTINUATION_SURFACES
    entry), so unfiltered it also fired `draft.continuation` -- stacking a
    competing `draft` score on top of the message's own, much more specific
    `revise.explicit_request` hit (it names a concrete field, "kapanış", with
    an active draft open -- see REVISE_RULES's own docstring on why that's
    unambiguous) and silently outscoring it. "yap" here is the sentence's own
    verb, not a bare "go ahead" confirmation; nothing about brevity or the
    surface list alone can tell the difference, so the fix is to defer to
    whichever *other* explicit rule already fired instead."""
    scores = score_intents(
        "Kapanışı 'Saygılarımızla arz ederiz.' yap.", None, "draft", has_active_draft=True
    )

    assert "draft.continuation" not in scores.evidence
    assert "revise.explicit_request" in scores.evidence
    assert scores.ranked[0][0] == "revise"


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


def test_a_request_softener_resolves_to_assist_now_that_chat_and_document_qa_are_merged():
    """"Bunun cevabını sen yazar mısın?" carries no document phrase, only the
    structural question-with-a-document hint. Before the merge this needed a
    counter-signal to stop it winning the narrow, retrieval-only `document_qa`
    outright; now that reading and a plain conversational one are the same
    `assist` intent, resolving here confidently is the right outcome -- the
    assistant agent itself decides whether a tool call is warranted."""
    scores = score_intents("Bunun cevabını sen yazar mısın?", DOCUMENT)

    assert scores.ranked[0][0] == "assist"
    assert scores.scores["assist"] >= PRESENCE_FLOOR


def test_a_softener_does_not_prevent_a_real_content_question_from_resolving():
    scores = score_intents("Bu belgede ne yazdığını söyler misin?", DOCUMENT)

    assert scores.ranked[0][0] == "assist"


def test_a_definitional_softener_does_not_capture_a_document_specific_question():
    """"anlatır mısın" no longer sits in the definitional-question surfaces on
    its own: asking to explain a specific document's status is not a question
    about a general concept, even though it uses the same softener."""
    scores = score_intents("Şu belgeye bir göz atıp durumu anlatır mısın?", DOCUMENT)

    assert "assist.definitional_question" not in scores.evidence


def test_a_genuine_definitional_question_still_resolves_to_assist():
    """The removed bare softener phrases were redundant for every existing
    case: "ne demek" alone still carries the inversion category."""
    scores = score_intents("Resmi yazı ne demek, kısaca anlatır mısın?", None)

    assert scores.ranked[0][0] == "assist"
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

    assert "assist.memory_recall" in scores.evidence
    assert scores.ranked[0][0] == "assist"


# ===========================================================================
# revise.muhatap_statement -- a plain informational statement naming the
# draft's muhatap has no revise *verb* at all, so it scored nothing before
# this rule existed and fell to whatever weak filler was lying around (see
# Görev 2's "bilgi kısmı hiçbir yere yazılmıyor" bug).
# ===========================================================================
def test_a_muhatap_statement_is_evidence_for_revise_when_a_draft_is_open():
    scores = score_intents(
        "Muhatap Ankara Valiliği olsun.", document_id=None, has_active_draft=True
    )

    assert "revise.muhatap_statement" in scores.evidence
    assert scores.ranked[0][0] == "revise"


def test_a_muhatap_statement_scores_nothing_without_an_active_draft():
    """Gated the same way REVISE_RULES itself is -- with no draft open,
    "muhatap" alone has no revision to attach to."""
    scores = score_intents(
        "Muhatap Ankara Valiliği olsun.", document_id=None, has_active_draft=False
    )

    assert "revise.muhatap_statement" not in scores.evidence


def test_a_muhatap_question_is_not_read_as_a_revise_statement():
    """"Muhatap kim?" asks about the current value, not a request to change
    it -- ambiguous enough to leave to escalation rather than guess."""
    scores = score_intents("Muhatap kim?", document_id=None, has_active_draft=True)

    assert "revise.muhatap_statement" not in scores.evidence


def test_a_muhatap_statement_accumulates_with_an_explicit_revise_verb():
    """Evidence accumulates rather than one signal replacing the other --
    see the module's own opening note."""
    scores = score_intents(
        "Muhatap Ankara Valiliği olsun, ayrıca üslubu daha resmi yap.",
        document_id=None, has_active_draft=True,
    )

    assert "revise.muhatap_statement" in scores.evidence
    assert "revise.explicit_request" in scores.evidence
