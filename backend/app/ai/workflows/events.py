"""Progress events emitted by workflow nodes and consumed by the SSE stream.

Every node publishes through this module rather than reaching into
``config["configurable"]["status_queue"]`` itself. Two reasons:

1. The queue is optional. Non-streaming callers (document upload, tests, evals)
   run the same graphs with no queue attached, so every emit has to be a no-op
   in that case -- a check that was previously duplicated at each call site and
   omitted in some of them.
2. Sub-graph invocations must forward the parent ``config``. When they did not,
   the queue never reached the writer and editor nodes, so the UI showed no
   progress at all during the longest phase of the pipeline. :func:`child_config`
   makes the correct call shape hard to get wrong.
"""

import logging
from typing import Any, Mapping, Optional

from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

STATUS_QUEUE_KEY = "status_queue"


def get_status_queue(config: Optional[RunnableConfig]) -> Any:
    """Return the progress queue attached to a config, if any.

    Args:
        config: The LangGraph runnable config.

    Returns:
        The ``asyncio.Queue`` supplied by the caller, or None.
    """
    if not config:
        return None
    return (config.get("configurable") or {}).get(STATUS_QUEUE_KEY)


def child_config(config: Optional[RunnableConfig]) -> RunnableConfig:
    """Derive the config to pass into a sub-graph invocation.

    Carries the progress queue and the tracing callbacks down into nested
    graphs. Passing nothing (the previous behaviour) silently disabled both.

    Args:
        config: The parent node's config.

    Returns:
        A config safe to hand to ``sub_graph.ainvoke(..., config=...)``.
    """
    if not config:
        return {}
    child: RunnableConfig = {"configurable": dict(config.get("configurable") or {})}
    callbacks = config.get("callbacks")
    if callbacks:
        child["callbacks"] = callbacks
    return child


async def emit(config: Optional[RunnableConfig], payload: Mapping[str, Any]) -> None:
    """Publish one progress event, ignoring the absence of a consumer.

    Args:
        config: The node's runnable config.
        payload: The event body.
    """
    queue = get_status_queue(config)
    if queue is None:
        return
    try:
        await queue.put(dict(payload))
    except Exception:
        logger.warning("Could not publish progress event %s", payload.get("event"))


async def emit_node_start(
    config: Optional[RunnableConfig], node: str, label: str, message: str
) -> None:
    """Announce that a node has begun.

    Args:
        config: The node's runnable config.
        node: Machine-readable node identifier.
        label: Turkish display label.
        message: Turkish status line for the UI.
    """
    await emit(
        config,
        {"event": "node_start", "node": node, "label": label, "message": message},
    )


async def emit_node_end(
    config: Optional[RunnableConfig],
    node: str,
    label: str,
    message: str,
    result: Any = None,
) -> None:
    """Announce that a node has finished, with its result.

    Args:
        config: The node's runnable config.
        node: Machine-readable node identifier.
        label: Turkish display label.
        message: Turkish status line for the UI.
        result: The node's output, rendered by the client.
    """
    await emit(
        config,
        {
            "event": "node_end",
            "node": node,
            "label": label,
            "message": message,
            "result": result if result is not None else {},
        },
    )


async def emit_token(config: Optional[RunnableConfig], node: str, text: str) -> None:
    """Publish a generated text chunk for live rendering.

    Args:
        config: The node's runnable config.
        node: The node producing the text.
        text: The chunk.
    """
    await emit(config, {"event": "token", "node": node, "text": text})


async def emit_partial(
    config: Optional[RunnableConfig], key: str, value: Any
) -> None:
    """Publish an intermediate result the UI can render before the run ends.

    Lets the client show the classification the moment it exists rather than
    waiting for the draft, which is where most of the wall-clock time goes.

    Args:
        config: The node's runnable config.
        key: Result identifier (e.g. ``"classification"``).
        value: The partial payload.
    """
    await emit(config, {"event": "partial_result", "key": key, "value": value})
