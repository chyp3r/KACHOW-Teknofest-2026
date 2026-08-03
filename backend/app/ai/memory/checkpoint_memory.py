"""Conversation memory as a read-through over the planning graph's own state.

The planning graph already persists ``PlanningState.history`` per thread_id
through its ``AsyncPostgresSaver`` checkpointer (see
``app.infrastructure.checkpointing``). This module is not a second store --
it is a :class:`BaseMemory`-shaped view over that same state, for callers that
want the standard ``get_messages``/``add_message``/``clear`` interface rather
than reaching into the graph directly.

``app/ai/memory/{conversation,summary,vector_memory}.py`` each kept their own
Redis- or Qdrant-backed history alongside this one and were removed: a second
store keyed by the same session_id can disagree with the checkpoint after a
crash between the two writes, and the resume path (``ChatService.resume``)
would have had to reconcile them for no benefit history doesn't already get
from living inside the same checkpoint as the interrupt/resume state itself.
"""

import logging
from typing import Any, Dict, List

from app.ai.memory.base import BaseMemory

logger = logging.getLogger(__name__)


class CheckpointMemory(BaseMemory):
    """Read-only view of a thread's conversation history.

    Args:
        planning_graph: The compiled, checkpointer-backed planning graph.
    """

    def __init__(self, planning_graph: Any):
        self.planning_graph = planning_graph

    async def get_messages(self, session_id: str, **kwargs: Any) -> List[Dict[str, str]]:
        """Return the thread's conversation history, oldest first.

        Args:
            session_id: The checkpointer thread_id.

        Returns:
            The stored turns, or an empty list when the thread has no
            checkpoint (never run, or no checkpointer configured).
        """
        config = {"configurable": {"thread_id": session_id}}
        try:
            snapshot = await self.planning_graph.aget_state(config)
        except Exception:
            logger.debug("No checkpointed state for session %s", session_id)
            return []
        values = getattr(snapshot, "values", None) or {}
        return list(values.get("history") or [])

    async def add_message(
        self, session_id: str, role: str, content: str, **kwargs: Any
    ) -> None:
        """Not supported: history is written by the graph's own nodes.

        A message appended here would live outside the checkpoint the graph
        actually reads on the thread's next turn, so it would never be seen --
        silently accepting the call would be worse than refusing it.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "CheckpointMemory is read-only; conversation turns are appended by "
            "planning_graph's own nodes (see PlanningState.history)."
        )

    async def clear(self, session_id: str) -> None:
        """Not supported: no state-update API is wired for this read path.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("CheckpointMemory does not support clearing a thread's history.")
