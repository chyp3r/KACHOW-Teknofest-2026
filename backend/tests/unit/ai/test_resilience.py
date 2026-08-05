"""Unit tests for node budgets and what counts as worth retrying.

The distinction these lock down cost a 502 in a live demo. `node_timeout` raised
a bare `TimeoutError`, `TRANSIENT_ERRORS` contained `TimeoutError`, so a node that
merely ran past its budget was retried -- spending the budget a second time before
failing the whole request. Observed: `suggest_mevzuat` normally takes 28-34s
against a 70s budget, occasionally ran long, and turned into a 166s wait ending in
a 502 where the correct answer was already in hand.
"""

import asyncio

import httpx
import pytest

from app.ai.workflows.resilience import (
    IO_RETRY,
    LLM_RETRY,
    TRANSIENT_ERRORS,
    NodeBudgetExceeded,
    node_timeout,
)


# ==========================================
# What is worth retrying
# ==========================================
def test_a_dropped_connection_is_retried():
    """The case retries exist for: Ollama or Qdrant hung up mid-call."""
    assert issubclass(ConnectionError, TRANSIENT_ERRORS)
    assert issubclass(httpx.TimeoutException, TRANSIENT_ERRORS)


def test_budget_exhaustion_is_not_retried():
    """A node too slow once will be too slow again. Retrying it doubles the
    user's wait and still fails, instead of letting the node degrade."""
    assert not issubclass(NodeBudgetExceeded, TRANSIENT_ERRORS)


def test_a_bare_timeout_error_is_not_retried():
    """`TimeoutError` used to be in this tuple, which is what made budget
    exhaustion look retryable."""
    assert TimeoutError not in TRANSIENT_ERRORS


def test_both_retry_policies_share_the_transient_set():
    assert LLM_RETRY.retry_on == TRANSIENT_ERRORS
    assert IO_RETRY.retry_on == TRANSIENT_ERRORS


# ==========================================
# node_timeout
# ==========================================
@pytest.mark.asyncio
async def test_a_node_within_budget_returns_normally():
    @node_timeout("suggest_mevzuat")
    async def _node(_state):
        return {"ok": True}

    assert await _node({}) == {"ok": True}


@pytest.mark.asyncio
async def test_an_overrunning_node_raises_the_budget_error(monkeypatch):
    monkeypatch.setattr(
        "app.ai.workflows.resilience.node_budget", lambda *_args, **_kwargs: 0.05
    )

    @node_timeout("suggest_mevzuat")
    async def _node(_state):
        await asyncio.sleep(5)

    with pytest.raises(NodeBudgetExceeded) as excinfo:
        await _node({})

    # Names the node and its budget: a bare TimeoutError in a graph of six nodes
    # said nothing about which one gave up.
    assert "suggest_mevzuat" in str(excinfo.value)


@pytest.mark.asyncio
async def test_the_budget_error_is_not_caught_by_transient_handlers(monkeypatch):
    """The property that matters: a node overrunning its budget must fall
    through a `except TRANSIENT_ERRORS: raise` clause to the degradation path
    below it, not be re-raised for a retry."""
    monkeypatch.setattr(
        "app.ai.workflows.resilience.node_budget", lambda *_args, **_kwargs: 0.05
    )

    @node_timeout("suggest_mevzuat")
    async def _node(_state):
        await asyncio.sleep(5)

    degraded = False
    try:
        await _node({})
    except TRANSIENT_ERRORS:  # pragma: no cover - must not be taken
        pytest.fail("budget exhaustion was treated as a transient error")
    except Exception:
        degraded = True

    assert degraded


@pytest.mark.asyncio
async def test_a_transient_failure_still_propagates_for_retry(monkeypatch):
    """The decorator must not swallow the errors that *are* worth retrying."""
    monkeypatch.setattr(
        "app.ai.workflows.resilience.node_budget", lambda *_args, **_kwargs: 5.0
    )

    @node_timeout("suggest_mevzuat")
    async def _node(_state):
        raise ConnectionError("connection refused")

    with pytest.raises(ConnectionError):
        await _node({})
