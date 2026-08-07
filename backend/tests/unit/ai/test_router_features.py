"""Unit tests for the router's feature extraction.

The point of keeping every signal source as its own feature (rather than
pre-summing lexical/semantic/structural evidence the way the old ladder did)
is that the fusion layer, not this module, decides how much each one is
worth. These tests only guard that the raw evidence lands in the right slot.
"""

from app.ai.workflows.intent_scorer import score_intents
from app.ai.workflows.router_features import FEATURE_NAMES, RouterSignals, extract_features


def _signals(message, document_id=None, semantic=None, has_active_draft=False, previous_intent=None):
    lexical = score_intents(message, document_id, previous_intent, has_active_draft)
    return RouterSignals(
        lexical=lexical,
        semantic=semantic,
        has_document=document_id is not None,
        has_active_draft=has_active_draft,
        previous_intent=previous_intent,
    )


def test_every_declared_feature_is_present():
    features = extract_features("Merhaba", _signals("Merhaba"))
    assert set(features) == set(FEATURE_NAMES)


def test_lexical_scores_land_in_their_own_per_intent_slots():
    features = extract_features(
        "Bu evraka bir cevap yazısı hazırla.",
        _signals("Bu evraka bir cevap yazısı hazırla.", document_id="uploads/x.pdf"),
    )
    assert features["lex_draft"] > 0.0
    assert features["lex_analyze"] == 0.0


def test_semantic_similarities_land_in_their_own_per_intent_slots():
    semantic = {"draft": 0.81, "analyze": 0.4, "assist": 0.3}
    features = extract_features("bir mesaj", _signals("bir mesaj", semantic=semantic))

    assert features["sem_draft"] == 0.81
    assert features["sem_analyze"] == 0.4
    assert features["sem_assist"] == 0.3
    # `revise` had no entry in the matcher's result -- absence is 0.0, not a
    # KeyError, since a family's vector file need not cover every intent.
    assert features["sem_revise"] == 0.0


def test_an_unknown_semantic_label_is_silently_ignored():
    """The vector file is data on disk; a label that maps to nothing in
    `router_features._INTENTS` must not blow up feature extraction."""
    semantic = {"bilinmeyen_etiket": 0.99}
    features = extract_features("bir mesaj", _signals("bir mesaj", semantic=semantic))

    assert features["sem_draft"] == 0.0
    assert features["sem_analyze"] == 0.0
    assert features["sem_assist"] == 0.0
    assert features["sem_revise"] == 0.0


def test_no_semantic_evidence_defaults_every_sem_feature_to_zero():
    features = extract_features("bir mesaj", _signals("bir mesaj", semantic=None))
    for intent in ("draft", "analyze", "assist", "revise"):
        assert features[f"sem_{intent}"] == 0.0


def test_document_and_active_draft_flags_are_boolean_features():
    with_both = extract_features(
        "bir mesaj",
        _signals("bir mesaj", document_id="uploads/x.pdf", has_active_draft=True),
    )
    assert with_both["has_document"] == 1.0
    assert with_both["has_active_draft"] == 1.0

    with_neither = extract_features("bir mesaj", _signals("bir mesaj"))
    assert with_neither["has_document"] == 0.0
    assert with_neither["has_active_draft"] == 0.0


def test_is_question_reflects_the_lexical_layers_own_heuristic():
    question = extract_features(
        "Bu belgede kimin imzası var?",
        _signals("Bu belgede kimin imzası var?", document_id="uploads/x.pdf"),
    )
    statement = extract_features(
        "Bu belgeye bir cevap yazısı hazırla.",
        _signals("Bu belgeye bir cevap yazısı hazırla.", document_id="uploads/x.pdf"),
    )
    assert question["is_question"] == 1.0
    assert statement["is_question"] == 0.0


def test_word_count_is_normalised_and_capped():
    short = extract_features("Cevap yaz.", _signals("Cevap yaz."))
    long_message = " ".join(["kelime"] * 30)
    long = extract_features(long_message, _signals(long_message))

    assert 0.0 < short["word_count_norm"] < 1.0
    assert long["word_count_norm"] == 1.0


def test_previous_intent_sets_exactly_one_continuation_flag():
    features = extract_features("evet", _signals("evet", previous_intent="revise"))

    assert features["prev_revise"] == 1.0
    assert features["prev_draft"] == 0.0
    assert features["prev_analyze"] == 0.0


def test_an_unknown_previous_intent_sets_no_continuation_flag():
    """`assist` (and `chat`/`document_qa`, from before the merge) has no
    unambiguous follow-up action -- see `CONTINUABLE_INTENTS`."""
    features = extract_features("evet", _signals("evet", previous_intent="assist"))

    assert features["prev_draft"] == 0.0
    assert features["prev_analyze"] == 0.0
    assert features["prev_revise"] == 0.0
