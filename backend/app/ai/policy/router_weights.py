"""Fitted coefficients for the router's calibrated fusion layer.

GENERATED FILE -- do not hand-edit. Produced by ``scripts/fit_router.py`` from
``evaluation/datasets/intents.jsonl``. Rerun that script (and commit the
result) after changing the training-relevant slice of the gold set, the
feature set in ``app.ai.workflows.router_features``, or ``POLICY_VERSION``.

Fitted 2026-08-07T10:26:05Z against 116 training rows (see
``scripts/fit_router.py``'s module docstring for which gold-set categories
are excluded and why). 5-fold cross-validation accuracy at fit time:
1.0000 -- the number to compare a refit against, not training
accuracy, which a model this size will always overfit toward on a few
hundred rows.
"""

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from app.ai.policy import POLICY_VERSION
from app.ai.workflows.router_features import FEATURE_NAMES
from app.ai.workflows.router_fusion import INTENTS

logger = logging.getLogger(__name__)

__all__ = ["RouterWeights", "ROUTER_WEIGHTS"]


@dataclass(frozen=True)
class RouterWeights:
    """The fusion layer's fitted linear coefficients, one set per intent.

    Attributes:
        version: The ``POLICY_VERSION`` this fit was produced under. Checked
            against the running policy below (a warning, not a hard failure --
            unlike a stale semantic-prototype file, there is no fallback state
            for the router to degrade to if these coefficients were refused:
            fusion *is* the decision mechanism now, not an optional layer a
            missing file can simply skip).
        feature_names: The exact feature order these coefficients were fit
            against. Validated against ``router_features.FEATURE_NAMES`` at
            import time -- a genuine structural mismatch here, unlike a stale
            version stamp, would make every score silently wrong, so this one
            *is* fatal.
        bias: Intent -> per-class bias term.
        coefficients: Intent -> feature name -> weight.
    """

    version: str
    feature_names: tuple[str, ...]
    bias: Mapping[str, float]
    coefficients: Mapping[str, Mapping[str, float]]

    def __post_init__(self) -> None:
        if self.feature_names != FEATURE_NAMES:
            raise ValueError(
                "RouterWeights.feature_names does not match the running "
                "router_features.FEATURE_NAMES -- rerun scripts/fit_router.py."
            )
        if set(self.bias) != set(INTENTS) or set(self.coefficients) != set(INTENTS):
            raise ValueError("RouterWeights must cover exactly router_fusion.INTENTS.")
        for intent in INTENTS:
            if set(self.coefficients[intent]) != set(FEATURE_NAMES):
                raise ValueError(
                    f"RouterWeights.coefficients[{intent!r}] does not cover every "
                    "feature in FEATURE_NAMES -- rerun scripts/fit_router.py."
                )


ROUTER_WEIGHTS = RouterWeights(
    version='1.5.0',
    feature_names=(
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
    "prev_revise"
    ),
    bias=MappingProxyType(
        {
        "draft": 0.206531,
        "analyze": -0.031590,
        "assist": -0.109431,
        "revise": -0.065510
        }
    ),
    coefficients=MappingProxyType(
        {
        "draft": MappingProxyType(
        {
            "lex_draft": 1.182636,
            "lex_analyze": -0.423505,
            "lex_assist": -0.302615,
            "lex_revise": -0.227798,
            "lex_margin": -0.086665,
            "sem_draft": 0.042651,
            "sem_analyze": -0.008984,
            "sem_assist": 0.028076,
            "sem_revise": 0.016173,
            "has_document": -0.048104,
            "has_active_draft": -0.075933,
            "is_question": -0.147658,
            "word_count_norm": 0.009579,
            "prev_draft": -0.037231,
            "prev_analyze": -0.009746,
            "prev_revise": 0.000000,
        }
    ),
        "analyze": MappingProxyType(
        {
            "lex_draft": -0.218278,
            "lex_analyze": 1.156761,
            "lex_assist": -0.422407,
            "lex_revise": -0.190500,
            "lex_margin": -0.077776,
            "sem_draft": 0.015130,
            "sem_analyze": 0.015278,
            "sem_assist": 0.002930,
            "sem_revise": 0.005745,
            "has_document": 0.235017,
            "has_active_draft": -0.063500,
            "is_question": -0.017906,
            "word_count_norm": 0.058254,
            "prev_draft": 0.080620,
            "prev_analyze": 0.039328,
            "prev_revise": 0.000000,
        }
    ),
        "assist": MappingProxyType(
        {
            "lex_draft": -0.702509,
            "lex_analyze": -0.531324,
            "lex_assist": 0.773719,
            "lex_revise": -0.597197,
            "lex_margin": 0.449070,
            "sem_draft": -0.030161,
            "sem_analyze": 0.013236,
            "sem_assist": -0.000278,
            "sem_revise": -0.028129,
            "has_document": -0.066253,
            "has_active_draft": -0.199066,
            "is_question": 0.227581,
            "word_count_norm": -0.066127,
            "prev_draft": -0.016524,
            "prev_analyze": -0.022782,
            "prev_revise": 0.000000,
        }
    ),
        "revise": MappingProxyType(
        {
            "lex_draft": -0.261849,
            "lex_analyze": -0.201932,
            "lex_assist": -0.048696,
            "lex_revise": 1.015495,
            "lex_margin": -0.284628,
            "sem_draft": -0.027620,
            "sem_analyze": -0.019530,
            "sem_assist": -0.030727,
            "sem_revise": 0.006211,
            "has_document": -0.120660,
            "has_active_draft": 0.338498,
            "is_question": -0.062017,
            "word_count_norm": -0.001705,
            "prev_draft": -0.026865,
            "prev_analyze": -0.006801,
            "prev_revise": 0.000000,
        }
    )
        }
    ),
)

if ROUTER_WEIGHTS.version != POLICY_VERSION:
    logger.warning(
        "Router fusion weights were fit under policy %s but %s is active -- "
        "scoring with a policy-stale (but structurally valid) model. Rerun "
        "scripts/fit_router.py.",
        ROUTER_WEIGHTS.version,
        POLICY_VERSION,
    )
