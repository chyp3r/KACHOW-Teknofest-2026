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

import asyncio
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


#: Characters per chunk in :func:`emit_reply_stream`. This is intentionally
#: smaller than a transport-oriented batch: the browser should visibly paint
#: the answer as it arrives instead of receiving the whole validated reply in
#: one render pass.
_REPLY_STREAM_CHUNK_SIZE = 24

#: Brief pacing between chunks. ``asyncio.Queue.put`` on an unbounded queue
#: completes synchronously, so without an explicit yield the producer queues
#: every token event plus ``final_result`` before the SSE consumer gets a turn.
#: Apart from defeating the typing animation, React then batches all updates
#: into a single render.
_REPLY_STREAM_CHUNK_DELAY_SECONDS = 0.025


async def emit_reply_stream(
    queue: Any,
    text: str,
    *,
    node: str = "reply",
    chunk_size: int = _REPLY_STREAM_CHUNK_SIZE,
    chunk_delay_seconds: float = _REPLY_STREAM_CHUNK_DELAY_SECONDS,
) -> None:
    """Stream a validated final reply to the client, chunk by chunk.

    The *only* place a ``token`` event is emitted post the draft/assist/
    revise validation rework (see ``draft_graph.writer_node``,
    ``planning_graph._run_assist``, ``revise_graph.rewrite_node``, none of
    which call ``emit_token`` anymore) -- called once, from
    ``app.domains.chat.chat_service._enqueue_terminal_event``, on the exact
    text ``final_result`` is about to carry. This is what makes "what
    streamed into the chat bubble" and "the turn's final answer" the same
    text by construction rather than by convention: nothing upstream of this
    call ever reaches the client's token handler, so there is nothing for a
    guardrail/verify pass to have silently changed out from under what the
    user already saw.

    Takes the raw queue directly, not a ``RunnableConfig`` -- this runs after
    the graph invocation has already returned, so there is no node config in
    scope, only the same ``asyncio.Queue`` that was attached to it as
    ``status_queue``.

    Args:
        queue: The SSE progress queue, or None (a no-op, same as :func:`emit`).
        text: The validated final reply.
        node: Node id carried on each token event -- purely informational;
            no node clears a live preview on its own ``node_start`` anymore
            (there is nothing left upstream that would stream one).
        chunk_size: Characters per emitted chunk.
        chunk_delay_seconds: Delay between chunks. This yields to the SSE
            consumer and gives the frontend a visible typing cadence. Tests
            can set it to zero without changing production pacing.
    """
    if queue is None or not text:
        return
    try:
        for start in range(0, len(text), chunk_size):
            await queue.put(
                {
                    "event": "token",
                    "node": node,
                    "text": text[start : start + chunk_size],
                    "seq": _next_seq(queue),
                }
            )
            if start + chunk_size < len(text) and chunk_delay_seconds > 0:
                await asyncio.sleep(chunk_delay_seconds)
    except Exception:
        logger.warning("Could not stream final reply")


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
        kind: ``"missing_information"``, ``"writing_brief"``,
            ``"artifact_transfer_confirm"`` or
            ``"artifact_transfer_disambiguate"``.
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


async def emit_guardrail_event(
    config: Optional[RunnableConfig],
    *,
    stage: str,
    kind: str,
    decision: str,
    reasons: Optional[list[str]] = None,
) -> None:
    """Publish a guardrail decision so the frontend can badge it live.

    Only called for a decision that actually did something -- flagged,
    blocked, redacted, needs_review -- never a routine "passed", which has
    nothing for the UI to show. The node emitting this already runs inside
    a graph invocation carrying the Langfuse callback (see
    ``build_trace_config``), so the decision lands in that trace without any
    extra plumbing here; ``GuardrailEventModel``
    (``app.observability.guardrail_recorder``) remains the durable audit
    record, this is only the live/UI side.

    Args:
        config: The node's runnable config.
        stage: "input" or "output".
        kind: See ``guardrail_recorder.record_event``.
        decision: "flagged" | "blocked" | "redacted" | "needs_review".
        reasons: Short human-readable reasons -- never the raw sensitive
            value that triggered the decision.
    """
    await emit(
        config,
        {
            "event": "guardrail",
            "stage": stage,
            "kind": kind,
            "decision": decision,
            "reasons": list(reasons or []),
        },
    )


async def emit_notice(
    config: Optional[RunnableConfig],
    *,
    node: str,
    title: str,
    message: str,
    level: str = "info",
) -> None:
    """Publish a non-blocking, informational message as its own chat turn.

    The non-pausing counterpart to :func:`emit_interrupt`. Use this for a
    finding that must be surfaced but must never gate the run -- an
    instruction/mevzuat conflict is the motivating case (see
    ``app.ai.revision.conflict``'s ``applied_anyway`` invariant: the edit
    already happened, this is only telling the user about a wrinkle in it).
    The frontend renders it as its own assistant message rather than folding
    it into the streamed reply, so a warning about round 1 never gets
    concatenated onto round 2's text the way raw token streaming would.

    Args:
        config: The node's runnable config.
        node: Which node raised this notice (e.g. ``"revise_audit"``).
        title: Short Turkish heading.
        message: The full Turkish notice text.
        level: Severity; only ``"info"`` exists today.
    """
    await emit(
        config,
        {
            "event": "notice",
            "node": node,
            "level": level,
            "title": title,
            "message": message,
        },
    )


async def emit_question(
    config: Optional[RunnableConfig],
    *,
    node: str,
    question: str,
    options: list[dict[str, str]],
    allow_free_text: bool = True,
    questions: Optional[list[dict[str, Any]]] = None,
) -> None:
    """Publish a decision the run needs, offered as clickable options.

    Unlike :func:`emit_interrupt`, this never pauses a LangGraph run via
    ``interrupt()`` -- the clarify step already ends its own turn
    deterministically and simply waits for the user's next message, which
    ``app.ai.workflows.planner._try_resolve_pending_clarification`` resolves
    against these same options. This event only tells the client to render
    them as a card instead of leaving the user to retype a label verbatim.

    Args:
        config: The node's runnable config.
        node: Which node raised this question (``"clarify"`` today).
        question: The Turkish question text.
        options: ``[{"value": ..., "label": ...}, ...]``.
        allow_free_text: Whether a typed reply can also resolve this
            question. Always True today.
        questions: The canonical ``PromptQuestion``-shaped list this event
            carries. Omitted by every caller today (``_step_clarify`` only
            ever asks one question) -- when absent, a single-element list is
            built from ``question``/``options``/``allow_free_text`` so old
            and new clients see the same content either way.
    """
    await emit(
        config,
        {
            "event": "question",
            "node": node,
            "question": question,
            "options": list(options),
            "allow_free_text": allow_free_text,
            "questions": questions
            if questions is not None
            else [
                {
                    "key": node,
                    "question": question,
                    "options": list(options),
                    "allow_free_text": allow_free_text,
                    "multi_select": False,
                    "required": True,
                }
            ],
        },
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
