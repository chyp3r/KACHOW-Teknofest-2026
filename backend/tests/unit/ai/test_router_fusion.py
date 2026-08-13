"""Unit tests for the pure-arithmetic fusion layer.

Deliberately built against a small synthetic `RouterWeights`, not the real
fitted `ROUTER_WEIGHTS` -- these tests guard the *arithmetic*
(`softmax`/`predict_proba`), not any particular fit's numbers.
"""

import math
from types import MappingProxyType

import pytest

from app.ai.workflows.router_features import FEATURE_NAMES
from app.ai.workflows.router_fusion import INTENTS, predict_proba, softmax


def _weights(**per_intent_bias):
    """A `RouterWeights`-shaped object with every coefficient at 0.0 except
    the per-intent biases supplied by the caller."""
    from app.ai.policy.router_weights import RouterWeights

    zeroed = MappingProxyType({name: 0.0 for name in FEATURE_NAMES})
    return RouterWeights(
        version="test",
        feature_names=FEATURE_NAMES,
        bias=MappingProxyType({intent: per_intent_bias.get(intent, 0.0) for intent in INTENTS}),
        coefficients=MappingProxyType({intent: zeroed for intent in INTENTS}),
    )


def test_softmax_sums_to_one():
    probs = softmax({"a": 1.0, "b": 2.0, "c": -1.0})
    assert math.isclose(sum(probs.values()), 1.0, rel_tol=1e-9)


def test_softmax_is_uniform_for_equal_logits():
    probs = softmax({"a": 5.0, "b": 5.0, "c": 5.0, "d": 5.0})
    for value in probs.values():
        assert math.isclose(value, 0.25, rel_tol=1e-9)


def test_softmax_handles_empty_input():
    assert softmax({}) == {}


def test_softmax_is_shift_invariant():
    """Adding a constant to every logit must not change the distribution --
    this is what the max-subtraction overflow guard relies on."""
    a = softmax({"x": 10.0, "y": -10.0})
    b = softmax({"x": 1010.0, "y": 990.0})
    assert math.isclose(a["x"], b["x"], rel_tol=1e-6)


def test_predict_proba_all_zero_features_reduces_to_softmax_of_the_biases():
    weights = _weights(draft=2.0, analyze=0.0, assist=0.0, revise=0.0)
    zero_features = {name: 0.0 for name in FEATURE_NAMES}

    probs = predict_proba(zero_features, weights)

    assert probs["draft"] > probs["analyze"] == probs["assist"] == probs["revise"]
    assert math.isclose(sum(probs.values()), 1.0, rel_tol=1e-9)


def test_predict_proba_ignores_a_feature_not_covered_by_the_weights():
    """A caller passing an extra key (e.g. from a future feature not yet
    trained on) must not raise -- only the weighted features count."""
    weights = _weights()
    features = {name: 0.0 for name in FEATURE_NAMES}
    features["some_future_feature"] = 999.0

    probs = predict_proba(features, weights)
    for value in probs.values():
        assert math.isclose(value, 0.25, rel_tol=1e-9)
