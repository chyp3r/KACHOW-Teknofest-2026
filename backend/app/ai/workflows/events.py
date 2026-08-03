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
import weakref
from typing import Any, Mapping, Optional

from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

STATUS_QUEUE_KEY = "status_queue"

#: Per-queue (i.e. per SSE session) monotonic counter, so the frontend can
#: order and deduplicate events -- needed in particular for the interrupt
#: replay case: interrupt() re-runs everything before it on resume, so
#: emit_interrupt fires again with the same interrupt_id, and seq is what
#: lets the client tell "the same event, replayed" from "a new one".
#: WeakKeyDictionary so a finished session's counter is freed with its queue
#: instead of accumulating for the life of the process.
_SEQUENCE_COUNTERS: "weakref.WeakKeyDictionary[Any, int]" = weakref.WeakKeyDictionary()


def _next_seq(queue: Any) -> int:
    """Return the next monotonic sequence number for a given progress queue."""
    current = _SEQUENCE_COUNTERS.get(queue, 0) + 1
    _SEQUENCE_COUNTERS[queue] = current
    return current


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
        enriched = dict(payload)
        enriched["seq"] = _next_seq(queue)
        await queue.put(enriched)
    except Exception:
        logger.warning("Could not publish progress event %s", payload.get("event"))


async def emit_node_start(
    config: Optional[RunnableConfig],
    node: str,
    label: str,
    message: str,
    meta: Optional[Mapping[str, Any]] = None,
) -> None:
    """Announce that a node has begun.

    Args:
        config: The node's runnable config.
        node: Machine-readable node identifier.
        label: Turkish display label.
        message: Turkish status line for the UI.
        meta: Optional extra fields (e.g. ``{"attempt": 2}`` on a draft
            revision) that do not fit the fixed event shape. A second draft
            attempt reuses the ``"draft"`` node id and streams under it again,
            so the frontend clears any in-progress ``streamingText`` on every
            ``node_start`` rather than only the first -- this is what makes
            that safe instead of concatenating two drafts together.
    """
    await emit(
        config,
        {
            "event": "node_start",
            "node": node,
            "label": label,
            "message": message,
            "meta": dict(meta) if meta else {},
        },
    )


async def emit_node_end(
    config: Optional[RunnableConfig],
    node: str,
    label: str,
    message: str,
    result: Any = None,
    meta: Optional[Mapping[str, Any]] = None,
) -> None:
    """Announce that a node has finished, with its result.

    Args:
        config: The node's runnable config.
        node: Machine-readable node identifier.
        label: Turkish display label.
        message: Turkish status line for the UI.
        result: The node's output, rendered by the client.
        meta: Optional extra fields; see :func:`emit_node_start`.
    """
    await emit(
        config,
        {
            "event": "node_end",
            "node": node,
            "label": label,
            "message": message,
            "result": result if result is not None else {},
            "meta": dict(meta) if meta else {},
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


async def emit_node_error(
    config: Optional[RunnableConfig],
    node: str,
    label: str,
    message: str,
    *,
    fatal: bool = True,
    detail: str = "",
) -> None:
    """Announce that a node failed or degraded.

    Args:
        config: The node's runnable config.
        node: Machine-readable node identifier.
        label: Turkish display label.
        message: Turkish status line for the UI.
        fatal: False for a degraded-but-continuing outcome (e.g. the judge
            call failing, which does not stop the draft flow), True for a
            failure that ends the run. The frontend node turns red either way
            but a non-fatal error keeps the rest of the run legible instead of
            reading as a crash.
        detail: Optional technical detail, not shown by default.
    """
    await emit(
        config,
        {
            "event": "node_error",
            "node": node,
            "label": label,
            "message": message,
            "fatal": fatal,
            "detail": detail,
        },
    )


async def emit_node_skipped(
    config: Optional[RunnableConfig], node: str, label: str, reason: str
) -> None:
    """Announce that a step was skipped because a dependency it needs failed.

    Without this, a step whose dependency failed (e.g. routing when the draft
    it would route just failed) silently ran anyway on empty input, and the
    resulting human-approval outcome was visually indistinguishable from a
    real routing decision. Skipping the step and saying why fixes both the
    behaviour and its visibility.

    Args:
        config: The node's runnable config.
        node: Machine-readable node identifier.
        label: Turkish display label.
        reason: Turkish explanation of why the step did not run.
    """
    await emit(
        config,
        {"event": "node_skipped", "node": node, "label": label, "reason": reason},
    )


async def emit_interrupt(
    config: Optional[RunnableConfig],
    *,
    kind: str,
    interrupt_id: str,
    payload: Mapping[str, Any],
) -> None:
    """Announce that the run has paused, waiting on a human response.

    A node that calls ``interrupt()`` re-executes everything before that call
    on resume, including this emit -- so callers derive ``interrupt_id``
    deterministically from state (never from a freshly generated UUID), and
    the frontend deduplicates on it rather than treating each emission as a
    new interrupt.

    Args:
        config: The node's runnable config.
        kind: ``"missing_information"`` or ``"draft_approval"``.
        interrupt_id: Stable id for this interrupt occurrence.
        payload: The data the human needs to answer -- questions, draft text,
            verification/judge results.
    """
    await emit(
        config,
        {
            "event": "interrupt",
            "kind": kind,
            "interrupt_id": interrupt_id,
            "payload": dict(payload),
        },
    )


async def emit_tool_call(
    config: Optional[RunnableConfig], node: str, tool: str, args: Mapping[str, Any]
) -> None:
    """Publish that the assistant agent invoked a tool for this turn.

    Args:
        config: The node's runnable config.
        node: The node running the tool loop (``"assist"``).
        tool: The tool's name, as declared in its ``ToolSpec``.
        args: The arguments the model supplied.
    """
    await emit(
        config,
        {"event": "tool_call", "node": node, "tool": tool, "args": dict(args)},
    )


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
