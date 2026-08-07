"""Combines the router's feature vector into one calibrated probability per intent.

A multinomial logistic model (four one-vs-rest linear scores through a
softmax), evaluated as plain Python arithmetic over a handful of floats --
no numpy, no inference framework. The coefficients live in
``app.ai.policy.router_weights`` as a frozen dataclass fitted offline by
``scripts/fit_router.py`` against ``evaluation/datasets/intents.jsonl``, the
same "fit once, freeze, check in the numbers" shape as
``scripts/build_prototypes.py``'s vectors.

Why a learned combination instead of another hand-picked weight table: the
table this replaces (``WEIGHT_EXPLICIT``/``WEIGHT_HINT``/... in
``intent_rules.py``) already *is* a manually-tuned linear combination, just
tuned by eye against whichever examples came to mind while writing it. The
K2 regression (an explicit imperative losing to a structural hint by a
margin of 0.2) is exactly the failure mode of hand-tuning: the weights were
never checked against the compound and structural rules firing *together* on
the same message. A model fit against the whole gold set at once, with the
same regularisation term penalising every coefficient, doesn't have that blind
spot -- it either learns that an explicit hit should dominate a structural
hint, or the gold set doesn't actually support that claim, and either way the
answer is measured rather than guessed.
"""

import math
from typing import TYPE_CHECKING

from app.ai.workflows.intent_rules import Intent
from app.ai.workflows.router_features import FEATURE_NAMES

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from app.ai.policy.router_weights import RouterWeights

__all__ = ["INTENTS", "predict_proba", "softmax"]

#: Fixed class order. Matches `router_features._INTENTS` and
#: `RouterWeights.coefficients`'s keys; kept independent (not imported from
#: `router_features`) so this module's public contract doesn't secretly widen
#: to include that module's private ordering.
INTENTS: tuple[Intent, ...] = ("draft", "analyze", "assist", "revise")


def softmax(logits: dict[str, float]) -> dict[str, float]:
    """Turn per-class logits into a probability distribution.

    Args:
        logits: Class -> unnormalised score.

    Returns:
        Class -> probability, summing to 1.0.
    """
    if not logits:
        return {}
    # Subtract the max before exponentiating -- the classic overflow guard;
    # softmax is shift-invariant so this changes nothing but the numerics.
    ceiling = max(logits.values())
    exponentials = {label: math.exp(value - ceiling) for label, value in logits.items()}
    total = sum(exponentials.values())
    return {label: value / total for label, value in exponentials.items()}


def predict_proba(
    features: dict[str, float], weights: "RouterWeights"
) -> dict[str, float]:
    """Score a feature vector into a calibrated probability per intent.

    Args:
        features: Output of ``router_features.extract_features``, keyed by
            ``FEATURE_NAMES``.
        weights: The fitted coefficients.

    Returns:
        Intent -> probability in [0, 1], summing to 1.0.
    """
    logits: dict[str, float] = {}
    for intent in INTENTS:
        coefficients = weights.coefficients[intent]
        logit = weights.bias[intent]
        for name in FEATURE_NAMES:
            logit += coefficients.get(name, 0.0) * features.get(name, 0.0)
        logits[intent] = logit
    return softmax(logits)
