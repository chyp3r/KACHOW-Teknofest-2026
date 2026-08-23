"""Fitted coefficients for the router's calibrated fusion layer.

GENERATED FILE -- do not hand-edit. Produced by ``scripts/fit_router.py`` from
``evaluation/datasets/intents.jsonl``. Rerun that script (and commit the
result) after changing the training-relevant slice of the gold set, the
feature set in ``app.ai.workflows.router_features``, or ``POLICY_VERSION``.

Fitted 2026-08-14T21:03:59Z against 127 training rows (see
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
    version='3.0.0',
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
        "draft": 0.236768,
        "analyze": -0.013670,
        "assist": 0.094960,
        "revise": -0.318058
        }
    ),
    coefficients=MappingProxyType(
        {
        "draft": MappingProxyType(
        {
            "lex_draft": 1.173179,
            "lex_analyze": -0.398803,
            "lex_assist": -0.194612,
            "lex_revise": -0.247459,
            "lex_margin": -0.192871,
            "sem_draft": 0.040008,
            "sem_analyze": -0.004081,
            "sem_assist": 0.028567,
            "sem_revise": 0.016849,
            "has_document": -0.022023,
            "has_active_draft": -0.099590,
            "is_question": -0.147662,
            "word_count_norm": 0.010870,
            "prev_draft": -0.025933,
            "prev_analyze": -0.008913,
            "prev_revise": -0.008662,
        }
    ),
        "analyze": MappingProxyType(
        {
            "lex_draft": -0.201909,
            "lex_analyze": 1.159511,
            "lex_assist": -0.314900,
            "lex_revise": -0.235052,
            "lex_margin": -0.156536,
            "sem_draft": 0.014254,
            "sem_analyze": 0.015817,
            "sem_assist": -0.000102,
            "sem_revise": 0.002302,
            "has_document": 0.256082,
            "has_active_draft": -0.089091,
            "is_question": -0.025712,
            "word_count_norm": 0.055682,
            "prev_draft": 0.070327,
            "prev_analyze": 0.042009,
            "prev_revise": -0.005211,
        }
    ),
        "assist": MappingProxyType(
        {
            "lex_draft": -0.697781,
            "lex_analyze": -0.514159,
            "lex_assist": 0.931050,
            "lex_revise": -0.460115,
            "lex_margin": 0.237705,
            "sem_draft": -0.024211,
            "sem_analyze": 0.020473,
            "sem_assist": -0.000464,
            "sem_revise": -0.018418,
            "has_document": -0.069610,
            "has_active_draft": -0.099203,
            "is_question": 0.178681,
            "word_count_norm": -0.064116,
            "prev_draft": -0.004791,
            "prev_analyze": -0.017445,
            "prev_revise": 0.022145,
        }
    ),
        "revise": MappingProxyType(
        {
            "lex_draft": -0.273490,
            "lex_analyze": -0.246549,
            "lex_assist": -0.421538,
            "lex_revise": 0.942627,
            "lex_margin": 0.111702,
            "sem_draft": -0.030051,
            "sem_analyze": -0.032209,
            "sem_assist": -0.028002,
            "sem_revise": -0.000734,
            "has_document": -0.164449,
            "has_active_draft": 0.287883,
            "is_question": -0.005307,
            "word_count_norm": -0.002436,
            "prev_draft": -0.039603,
            "prev_analyze": -0.015651,
            "prev_revise": -0.008272,
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
