"""Centralised resilience primitives for LangGraph nodes.

LangGraph moved ``RetryPolicy`` between ``langgraph.pregel`` and
``langgraph.types`` across releases. Every module in this codebase that needs
it imports it from here, not from LangGraph directly, so a version bump only
needs one import path fixed instead of a grep-and-replace across every graph.
"""

import asyncio
import functools
import logging
from typing import Any, Awaitable, Callable, Optional, TypeVar

import httpx

from app.ai.policy import get_policy
from app.ai.policy.budget import node_budget

try:
    from langgraph.types import RetryPolicy
except ImportError:  # pragma: no cover - depends on the resolved langgraph version
    from langgraph.pregel import RetryPolicy  # type: ignore[no-redef,assignment]

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Transient failures worth a second attempt: a hung/dropped connection to
#: Ollama or Qdrant, not a validation error or a schema mismatch (those are
#: handled by BaseAgent.run_structured's own correction loop, not by retrying
#: the whole node).
TRANSIENT_ERRORS = (TimeoutError, ConnectionError, httpx.HTTPError, httpx.TimeoutException)

#: For LLM-backed nodes that do not stream tokens to the UI. Retrying a node
#: that already emitted tokens (the draft writer) would replay the whole
#: generation into the frontend's streamingText -- those nodes get resilience
#: from the reflexion loop instead (see draft_graph.py), never from this policy.
LLM_RETRY = RetryPolicy(
    max_attempts=2,
    initial_interval=0.5,
    backoff_factor=2.0,
    retry_on=TRANSIENT_ERRORS,
)

#: For retrieval / vector-store I/O, which is cheaper to retry than an LLM call.
IO_RETRY = RetryPolicy(
    max_attempts=3,
    initial_interval=0.3,
    backoff_factor=2.0,
    retry_on=TRANSIENT_ERRORS,
)

#: Per-node timeout budgets, kept as a module alias for readability at the call
#: sites that report them. The values live in ``app.ai.policy`` so they sit
#: beside the invariants that relate them to the workflow ceiling.
NODE_TIMEOUT_SECONDS = get_policy().budget.node_seconds


def _reasoning_level_of(args: tuple[Any, ...]) -> Optional[str]:
    """Read the run's reasoning level out of a LangGraph node's state argument.

    Args:
        args: The wrapped node's positional arguments. LangGraph always passes
            state first.

    Returns:
        The level, or None when the graph's state carries no such field --
        ``DocumentAnalysisState`` and ``RoutingState`` do not, and budget
        resolution falls back to balanced for them.
    """
    state = args[0] if args else None
    if isinstance(state, dict):
        level = state.get("reasoning_level")
        return level if isinstance(level, str) else None
    return None


def node_timeout(
    node: str,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator wrapping an async node in a budget resolved at call time.

    Takes a node *name* rather than a number on purpose. The previous signature
    took a float, which was evaluated when the graph was built -- and a graph is
    compiled once per process, so no per-request value could ever reach it. That
    is why ``reasoning_levels.timeout_multiplier`` never affected a node budget
    despite existing since the feature landed.

    Args:
        node: The node's name, as keyed in ``BudgetPolicy.node_seconds``.

    Returns:
        The decorator.
    """

    def _decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def _wrapped(*args: Any, **kwargs: Any) -> T:
            budget = node_budget(node, _reasoning_level_of(args))
            return await asyncio.wait_for(func(*args, **kwargs), timeout=budget)

        return _wrapped

    return _decorator


async def with_fast_tier_fallback(
    primary: Callable[[], Awaitable[T]],
    fallback: Callable[[], Awaitable[T]],
) -> T:
    """Run ``primary``; on failure, run ``fallback`` once.

    Used to drop from the quality tier to the fast tier on the *failure path
    only* -- the common case never pays the fallback's cost. This is the
    third rung under the document-analysis node's existing two-tier
    degradation ladder (merged schema -> classification-only -> this).

    Args:
        primary: The preferred call, already bound to its arguments.
        fallback: The degraded call, tried only if ``primary`` raises.

    Returns:
        The result of whichever call succeeded.

    Raises:
        Exception: The fallback's exception, if both attempts failed.
    """
    try:
        return await primary()
    except Exception:
        logger.warning("Primary call failed; falling back to the fast tier.", exc_info=True)
        return await fallback()
