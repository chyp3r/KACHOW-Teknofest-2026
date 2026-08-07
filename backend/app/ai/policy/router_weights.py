"""Fitted coefficients for the router's calibrated fusion layer.

GENERATED FILE -- do not hand-edit. Produced by ``scripts/fit_router.py`` from
``evaluation/datasets/intents.jsonl``. Rerun that script (and commit the
result) after changing the training-relevant slice of the gold set, the
feature set in ``app.ai.workflows.router_features``, or ``POLICY_VERSION``.

Fitted 2026-08-07T16:15:48Z against 127 training rows (see
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
    version='1.6.0',
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
        "draft": 0.246508,
        "analyze": -0.018133,
        "assist": 0.095662,
        "revise": -0.324036
        }
    ),
    coefficients=MappingProxyType(
        {
        "draft": MappingProxyType(
        {
            "lex_draft": 1.180990,
            "lex_analyze": -0.404125,
            "lex_assist": -0.206318,
            "lex_revise": -0.252834,
            "lex_margin": -0.184379,
            "sem_draft": 0.043872,
            "sem_analyze": -0.004412,
            "sem_assist": 0.027352,
            "sem_revise": 0.016614,
            "has_document": -0.013866,
            "has_active_draft": -0.101298,
            "is_question": -0.150363,
            "word_count_norm": 0.011664,
            "prev_draft": -0.031832,
            "prev_analyze": -0.009236,
            "prev_revise": -0.008644,
        }
    ),
        "analyze": MappingProxyType(
        {
            "lex_draft": -0.206212,
            "lex_analyze": 1.162825,
            "lex_assist": -0.310744,
            "lex_revise": -0.233554,
            "lex_margin": -0.159593,
            "sem_draft": 0.012550,
            "sem_analyze": 0.015986,
            "sem_assist": 0.000374,
            "sem_revise": 0.002354,
            "has_document": 0.252996,
            "has_active_draft": -0.088572,
            "is_question": -0.024697,
            "word_count_norm": 0.055261,
            "prev_draft": 0.073548,
            "prev_analyze": 0.042215,
            "prev_revise": -0.005195,
        }
    ),
        "assist": MappingProxyType(
        {
            "lex_draft": -0.697434,
            "lex_analyze": -0.513257,
            "lex_assist": 0.935369,
            "lex_revise": -0.458592,
            "lex_margin": 0.233606,
            "sem_draft": -0.024886,
            "sem_analyze": 0.020669,
            "sem_assist": 0.000084,
            "sem_revise": -0.018139,
            "has_document": -0.071652,
            "has_active_draft": -0.098863,
            "is_question": 0.179620,
            "word_count_norm": -0.064209,
            "prev_draft": -0.003903,
            "prev_analyze": -0.017382,
            "prev_revise": 0.022093,
        }
    ),
        "revise": MappingProxyType(
        {
            "lex_draft": -0.277344,
            "lex_analyze": -0.245443,
            "lex_assist": -0.418307,
            "lex_revise": 0.944979,
            "lex_margin": 0.110366,
            "sem_draft": -0.031536,
            "sem_analyze": -0.032243,
            "sem_assist": -0.027810,
            "sem_revise": -0.000829,
            "has_document": -0.167479,
            "has_active_draft": 0.288733,
            "is_question": -0.004560,
            "word_count_norm": -0.002715,
            "prev_draft": -0.037813,
            "prev_analyze": -0.015596,
            "prev_revise": -0.008254,
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
