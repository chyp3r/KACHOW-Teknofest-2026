"""Turns a message plus its context into the fusion layer's feature vector.

The old ladder let whichever rung answered first decide alone: the lexical
layer's margin gated everything, and the semantic rung only ever got a look
when the lexical layer had already abstained. That is why a message carrying
one explicit imperative and one structural hint (see the K2 regression --
"Cevap yaz." scoring `draft=3.0` against a `assist=2.0` hint from
`assist.short_message`, margin ``1.0 < 1.2``) fell through to a clarifying
question instead of resolving: the margin test cannot tell an explicit
imperative apart from a weak structural hint, because both are already
folded into the same per-intent sum.

This module keeps every signal source distinct instead of pre-summing them,
so ``router_fusion``'s calibrated weights can learn how much each one is
worth relative to the others -- an explicit lexical hit should outweigh a
structural hint by a learned amount, not by whatever the hand-picked
``WEIGHT_EXPLICIT``/``WEIGHT_HINT`` constants happened to produce.
"""

from dataclasses import dataclass
from typing import Optional

from app.ai.workflows.intent_rules import Intent
from app.ai.workflows.intent_scorer import IntentScores, looks_like_question, normalize

__all__ = ["FEATURE_NAMES", "extract_features"]

#: The four intents the fusion layer decides between. `clarify` is not one
#: of them -- it is what the decision *policy* falls back to when no intent's
#: fused probability clears the low threshold, not a class the model predicts.
_INTENTS: tuple[Intent, ...] = ("draft", "analyze", "assist", "revise")

#: Fixed feature order. `router_fusion.predict_proba` and `scripts/fit_router.py`
#: both iterate this tuple, so a feature can be added here without touching
#: either -- the weights dataclass just needs a matching entry, checked by
#: `RouterWeights.__post_init__` (see `app.ai.policy.router_weights`).
FEATURE_NAMES: tuple[str, ...] = (
    "lex_draft",
    "lex_analyze",
    "lex_assist",
    "lex_revise",
    "lex_margin",
    "sem_draft",
    "sem_analyze",
    "sem_assist",
    "sem_revise",
    "has_document",
    "has_active_draft",
    "is_question",
    "word_count_norm",
    "prev_draft",
    "prev_analyze",
    "prev_revise",
)


@dataclass(frozen=True)
class RouterSignals:
    """The raw evidence `extract_features` turns into a feature vector.

    Kept as a named, inspectable bundle (rather than passing five loose
    arguments) so a caller building it up in stages -- lexical always, semantic
    only when the matcher is available -- has one object to hand off.
    """

    lexical: IntentScores
    semantic: Optional[dict[str, float]]
    has_document: bool
    has_active_draft: bool
    previous_intent: Optional[str]


def extract_features(message: str, signals: RouterSignals) -> dict[str, float]:
    """Build the fusion layer's feature vector for one message.

    Args:
        message: The user's raw message (used for word count and the
            question-shape heuristic; matching itself was already done to
            produce ``signals.lexical``).
        signals: Every piece of evidence already gathered for this turn.

    Returns:
        Feature name -> value, keyed exactly by ``FEATURE_NAMES``.
    """
    normalized = normalize(message)
    words = normalized.split()

    features = {name: 0.0 for name in FEATURE_NAMES}

    for intent in _INTENTS:
        features[f"lex_{intent}"] = signals.lexical.scores.get(intent, 0.0)
    features["lex_margin"] = signals.lexical.margin

    if signals.semantic:
        for intent in _INTENTS:
            features[f"sem_{intent}"] = signals.semantic.get(intent, 0.0)

    features["has_document"] = 1.0 if signals.has_document else 0.0
    features["has_active_draft"] = 1.0 if signals.has_active_draft else 0.0
    features["is_question"] = 1.0 if looks_like_question(message, normalized) else 0.0
    # Capped rather than raw: a 4-word and a 40-word message should not be
    # ten times apart on a feature a linear model weighs alongside 0/1 flags.
    features["word_count_norm"] = min(len(words), 10) / 10.0

    if signals.previous_intent == "draft":
        features["prev_draft"] = 1.0
    elif signals.previous_intent == "analyze":
        features["prev_analyze"] = 1.0
    elif signals.previous_intent == "revise":
        features["prev_revise"] = 1.0

    return features
