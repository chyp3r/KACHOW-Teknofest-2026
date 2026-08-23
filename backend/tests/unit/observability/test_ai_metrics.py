"""Tests for `NODE_BUDGET_SECONDS` (H1) -- the Prometheus mirror of
`BudgetPolicy.node_seconds`, set once at process start so it can be
`join`'d against `NODE_DURATION`'s own observations in PromQL (see
`monitoring/prometheus/rules/kachow.rules.yml`'s `KachowNodeBudgetExhaustion`
rule)."""

from app.ai.policy import get_policy
from app.observability.ai_metrics import NODE_BUDGET_SECONDS, init_ai_metrics


def test_init_ai_metrics_sets_a_gauge_per_budget_node():
    init_ai_metrics()

    node_seconds = get_policy().budget.node_seconds
    assert node_seconds, "BudgetPolicy.node_seconds must not be empty for this test to mean anything"

    for node, seconds in node_seconds.items():
        value = NODE_BUDGET_SECONDS.labels(node=node)._value.get()
        assert value == seconds, f"NODE_BUDGET_SECONDS[{node}] = {value}, expected {seconds}"


def test_init_ai_metrics_is_idempotent():
    """main.py calls this once at import time, but re-running it (e.g. a
    second test importing the module) must not raise or leave stale
    labels -- Gauge.set() overwrites, it does not accumulate."""
    init_ai_metrics()
    init_ai_metrics()

    node, seconds = next(iter(get_policy().budget.node_seconds.items()))
    assert NODE_BUDGET_SECONDS.labels(node=node)._value.get() == seconds
