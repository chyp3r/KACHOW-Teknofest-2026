"""Fitted coefficients for the router's calibrated fusion layer.

GENERATED FILE -- do not hand-edit. Produced by ``scripts/fit_router.py`` from
``evaluation/datasets/intents.jsonl``. Rerun that script (and commit the
result) after changing the training-relevant slice of the gold set, the
feature set in ``app.ai.workflows.router_features``, or ``POLICY_VERSION``.

Fitted 2026-08-23T21:37:02Z against 127 training rows (see
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
    version='3.1.0',
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
        "draft": 0.240631,
        "analyze": -0.028418,
        "assist": 0.119046,
        "revise": -0.331259
        }
    ),
    coefficients=MappingProxyType(
        {
        "draft": MappingProxyType(
        {
            "lex_draft": 1.172616,
            "lex_analyze": -0.398989,
            "lex_assist": -0.194106,
            "lex_revise": -0.247832,
            "lex_margin": -0.191865,
            "sem_draft": 0.053277,
            "sem_analyze": 0.008134,
            "sem_assist": -0.005610,
            "sem_revise": 0.014800,
            "has_document": -0.021597,
            "has_active_draft": -0.099661,
            "is_question": -0.146715,
            "word_count_norm": 0.011476,
            "prev_draft": -0.025874,
            "prev_analyze": -0.009006,
            "prev_revise": -0.008644,
        }
    ),
        "analyze": MappingProxyType(
        {
            "lex_draft": -0.202439,
            "lex_analyze": 1.157235,
            "lex_assist": -0.314821,
            "lex_revise": -0.235578,
            "lex_margin": -0.157086,
            "sem_draft": 0.003501,
            "sem_analyze": 0.054610,
            "sem_assist": -0.010360,
            "sem_revise": 0.013691,
            "has_document": 0.255127,
            "has_active_draft": -0.089220,
            "is_question": -0.025908,
            "word_count_norm": 0.055082,
            "prev_draft": 0.070437,
            "prev_analyze": 0.042338,
            "prev_revise": -0.005193,
        }
    ),
        "assist": MappingProxyType(
        {
            "lex_draft": -0.695838,
            "lex_analyze": -0.511550,
            "lex_assist": 0.930695,
            "lex_revise": -0.458857,
            "lex_margin": 0.238776,
            "sem_draft": -0.040129,
            "sem_analyze": -0.040321,
            "sem_assist": 0.050827,
            "sem_revise": -0.039536,
            "has_document": -0.069486,
            "has_active_draft": -0.098790,
            "is_question": 0.177514,
            "word_count_norm": -0.063838,
            "prev_draft": -0.004925,
            "prev_analyze": -0.017610,
            "prev_revise": 0.022122,
        }
    ),
        "revise": MappingProxyType(
        {
            "lex_draft": -0.274340,
            "lex_analyze": -0.246696,
            "lex_assist": -0.421768,
            "lex_revise": 0.942267,
            "lex_margin": 0.110175,
            "sem_draft": -0.016649,
            "sem_analyze": -0.022422,
            "sem_assist": -0.034857,
            "sem_revise": 0.011045,
            "has_document": -0.164044,
            "has_active_draft": 0.287671,
            "is_question": -0.004891,
            "word_count_norm": -0.002719,
            "prev_draft": -0.039637,
            "prev_analyze": -0.015721,
            "prev_revise": -0.008285,
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
