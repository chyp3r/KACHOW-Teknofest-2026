"""Fitted coefficients for the router's calibrated fusion layer.

GENERATED FILE -- do not hand-edit. Produced by ``scripts/fit_router.py`` from
``evaluation/datasets/intents.jsonl``. Rerun that script (and commit the
result) after changing the training-relevant slice of the gold set, the
feature set in ``app.ai.workflows.router_features``, or ``POLICY_VERSION``.

Fitted 2026-08-07T14:31:16Z against 120 training rows (see
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
        "draft": 0.203618,
        "analyze": -0.035068,
        "assist": -0.107022,
        "revise": -0.061528
        }
    ),
    coefficients=MappingProxyType(
        {
        "draft": MappingProxyType(
        {
            "lex_draft": 1.176749,
            "lex_analyze": -0.418767,
            "lex_assist": -0.291662,
            "lex_revise": -0.238095,
            "lex_margin": -0.095981,
            "sem_draft": 0.041812,
            "sem_analyze": -0.008605,
            "sem_assist": 0.026042,
            "sem_revise": 0.014373,
            "has_document": -0.041010,
            "has_active_draft": -0.078874,
            "is_question": -0.159160,
            "word_count_norm": 0.007593,
            "prev_draft": -0.035735,
            "prev_analyze": -0.009700,
            "prev_revise": 0.000000,
        }
    ),
        "analyze": MappingProxyType(
        {
            "lex_draft": -0.215766,
            "lex_analyze": 1.151899,
            "lex_assist": -0.409788,
            "lex_revise": -0.202710,
            "lex_margin": -0.086097,
            "sem_draft": 0.013719,
            "sem_analyze": 0.015059,
            "sem_assist": 0.000730,
            "sem_revise": 0.003222,
            "has_document": 0.239464,
            "has_active_draft": -0.067036,
            "is_question": -0.030394,
            "word_count_norm": 0.055540,
            "prev_draft": 0.079627,
            "prev_analyze": 0.039477,
            "prev_revise": 0.000000,
        }
    ),
        "assist": MappingProxyType(
        {
            "lex_draft": -0.696821,
            "lex_analyze": -0.526266,
            "lex_assist": 0.783824,
            "lex_revise": -0.610233,
            "lex_margin": 0.431085,
            "sem_draft": -0.028750,
            "sem_analyze": 0.013309,
            "sem_assist": -0.001854,
            "sem_revise": -0.027827,
            "has_document": -0.058576,
            "has_active_draft": -0.201297,
            "is_question": 0.204606,
            "word_count_norm": -0.065943,
            "prev_draft": -0.016312,
            "prev_analyze": -0.022327,
            "prev_revise": 0.000000,
        }
    ),
        "revise": MappingProxyType(
        {
            "lex_draft": -0.264163,
            "lex_analyze": -0.206866,
            "lex_assist": -0.082374,
            "lex_revise": 1.051038,
            "lex_margin": -0.249007,
            "sem_draft": -0.026780,
            "sem_analyze": -0.019763,
            "sem_assist": -0.024918,
            "sem_revise": 0.010232,
            "has_document": -0.139878,
            "has_active_draft": 0.347206,
            "is_question": -0.015052,
            "word_count_norm": 0.002809,
            "prev_draft": -0.027580,
            "prev_analyze": -0.007450,
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
