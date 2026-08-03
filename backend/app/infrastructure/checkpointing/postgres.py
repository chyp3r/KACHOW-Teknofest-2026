"""Process-wide LangGraph checkpointer lifecycle.

``AsyncPostgresSaver.from_conn_string()`` is an async context manager, not a
plain constructor -- it owns a connection pool that is torn down the moment
the context exits. Awaiting and discarding it (the naive approach) would
close the pool before the first checkpoint write. Instead the context is
entered once, held open in an :class:`~contextlib.AsyncExitStack` for the
lifetime of the process, and closed explicitly at shutdown.

Best-effort by design, matching ``app.lifespan``: a missing or unreachable
Postgres, or the checkpoint packages not being installed, must not prevent
the API from booting. ``get_checkpointer()`` returning ``None`` means the
planning graph compiles without one -- Görev 1 and the non-interrupt half of
Görev 2 keep working; only human-in-the-loop (missing-info requests, draft
approval) becomes unavailable.
"""

import logging
from contextlib import AsyncExitStack
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_stack: Optional[AsyncExitStack] = None
_saver: Optional[Any] = None


async def init_checkpointer() -> Optional[Any]:
    """Open the checkpointer's connection pool and run its schema setup.

    Must be called before the planning graph is compiled, since the
    checkpointer is passed into ``StateGraph.compile(checkpointer=...)``.

    Returns:
        The ready :class:`AsyncPostgresSaver`, or ``None`` when checkpointing
        is disabled or unavailable.
    """
    global _stack, _saver

    if not settings.CHECKPOINTER_ENABLED:
        logger.info("Checkpointer disabled via settings; HITL is unavailable.")
        return None

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError:
        logger.warning(
            "langgraph-checkpoint-postgres is not installed; HITL is unavailable."
        )
        return None

    stack = AsyncExitStack()
    try:
        saver = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(settings.checkpointer_dsn)
        )
        # Idempotent: safe to run on every boot, including against a database
        # the checkpointer has already set up in a previous run.
        await saver.setup()
    except Exception:
        logger.warning(
            "Failed to initialise the LangGraph checkpointer; HITL is unavailable.",
            exc_info=True,
        )
        await stack.aclose()
        return None

    _stack = stack
    _saver = saver
    logger.info("LangGraph checkpointer ready.")
    return _saver


async def close_checkpointer() -> None:
    """Close the checkpointer's connection pool. Safe to call if never opened."""
    global _stack, _saver
    if _stack is not None:
        await _stack.aclose()
    _stack = None
    _saver = None


def get_checkpointer() -> Optional[Any]:
    """Return the process-wide checkpointer, or ``None`` if unavailable."""
    return _saver
