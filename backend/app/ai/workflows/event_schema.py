"""Typed contract for the SSE progress-event vocabulary.

``app.ai.workflows.events`` builds and pushes these as plain dicts (the queue
is a generic transport, not a place to pay Pydantic validation cost on every
token during a stream). This module exists so the *shape* of each event name
is written down once, in code, rather than only in prose -- and so
``tests/unit/ai/test_event_contract.py`` (Phase 11) can assert the frontend's
hand-written TypeScript union hasn't drifted from what the backend actually
emits, without standing up a Pydantic-to-TypeScript codegen step for ten
event types.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SessionEvent(BaseModel):
    """First event of every stream: the resolved checkpointer thread_id."""

    event: Literal["session"] = "session"
    thread_id: str
    seq: Optional[int] = None


class NodeStartEvent(BaseModel):
    event: Literal["node_start"] = "node_start"
    node: str
    label: str
    message: str
    meta: dict[str, Any] = Field(default_factory=dict)
    seq: Optional[int] = None


class NodeEndEvent(BaseModel):
    event: Literal["node_end"] = "node_end"
    node: str
    label: str
    message: str
    result: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)
    seq: Optional[int] = None


class NodeErrorEvent(BaseModel):
    event: Literal["node_error"] = "node_error"
    node: str
    label: str
    message: str
    fatal: bool = True
    detail: str = ""
    seq: Optional[int] = None


class NodeSkippedEvent(BaseModel):
    event: Literal["node_skipped"] = "node_skipped"
    node: str
    label: str
    reason: str
    seq: Optional[int] = None


class TokenEvent(BaseModel):
    event: Literal["token"] = "token"
    node: str
    text: str
    seq: Optional[int] = None


class ToolCallEvent(BaseModel):
    """The assistant agent invoked a tool for this turn (see ``app.ai.tools``)."""

    event: Literal["tool_call"] = "tool_call"
    node: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    seq: Optional[int] = None


class PartialResultEvent(BaseModel):
    event: Literal["partial_result"] = "partial_result"
    key: str
    value: Any
    seq: Optional[int] = None


class PlanningCompletedEvent(BaseModel):
    event: Literal["planning_completed"] = "planning_completed"
    plan_steps: list[str]
    intent: str
    reasoning: str
    #: Which mechanism produced this decision (``fused``/``fused_semantic``/
    #: ``compound``/``clarification_resolved``/``model``/``model_failed``/
    #: ``clarify`` -- see ``app.ai.workflows.planner.PlanDecision.source``).
    #: Surfaced so the frontend's decision-flow view can show *how* the
    #: router decided, not just what it decided.
    source: str = ""
    #: The decision's own confidence in [0, 1] -- comparable across every
    #: source since the fusion rewrite (see ``PlanDecision.confidence``).
    confidence: float = 1.0
    #: Runner-up intents with their probabilities, highest first.
    alternatives: list[tuple[str, float]] = Field(default_factory=list)
    seq: Optional[int] = None


class GuardrailEvent(BaseModel):
    """A guardrail decision that changed the response, published live.

    Was already emitted by ``app.ai.workflows.events.emit_guardrail_event``
    and consumed by the frontend's own ``GuardrailEvent`` type -- this class
    only backfills the missing typed contract entry so
    ``test_event_contract.py`` actually covers it, the same way every other
    event on the wire already is.
    """

    event: Literal["guardrail"] = "guardrail"
    stage: Literal["input", "output"]
    kind: str
    decision: Literal["flagged", "blocked", "redacted", "needs_review"]
    reasons: list[str] = Field(default_factory=list)
    seq: Optional[int] = None


class InterruptEvent(BaseModel):
    event: Literal["interrupt"] = "interrupt"
    kind: Literal["missing_information", "draft_approval", "writing_brief"]
    interrupt_id: str
    payload: dict[str, Any]
    seq: Optional[int] = None


class NoticeEvent(BaseModel):
    """A non-blocking, informational message rendered as its own chat turn.

    The counterpart to ``InterruptEvent``: an interrupt pauses the run and
    demands a human answer before anything else can happen (see
    ``langgraph.types.interrupt``); a notice never pauses anything -- the
    graph keeps running and the client only has to render one more bubble.
    Introduced so a finding that must never gate the run (an instruction/
    mevzuat conflict -- see ``app.ai.revision.conflict``'s
    ``applied_anyway`` invariant) has somewhere to go other than either
    silently vanishing into a result blob or, worse, forcing a popup the way
    a "revizyon" gate briefly did.
    """

    event: Literal["notice"] = "notice"
    node: str
    #: "info" today; the field exists so a future distinct severity (e.g. a
    #: guardrail-adjacent warning) doesn't need a second event type.
    level: Literal["info"] = "info"
    title: str
    message: str
    seq: Optional[int] = None


class QuestionOption(BaseModel):
    """One clickable answer to a ``PromptQuestion``/``QuestionEvent``."""

    value: str
    label: str
    #: Optional second line of explanation shown under the option's label.
    description: str = ""


class PromptQuestion(BaseModel):
    """One question in the canonical shape shared by every "ask the user"
    surface -- the pre-draft writing brief, missing-information requests,
    and clarify's intent question all publish ``list[PromptQuestion]`` so a
    single frontend card component can render all three.

    ``missing_information`` keeps its own ``InfoQuestion`` internally (its
    ``key`` is the join key ``apply_answers`` substitutes placeholders by)
    and only converts to this shape at the emit boundary, via
    ``InfoQuestion.to_prompt_question``.
    """

    key: str
    question: str
    header: str = ""
    #: Why this is being asked -- legal/regulatory justification or similar
    #: context. Mirrors ``InfoQuestion.why``.
    help: str = ""
    example: Optional[str] = None
    options: list[QuestionOption] = Field(default_factory=list)
    multi_select: bool = False
    allow_free_text: bool = True
    required: bool = True


class QuestionEvent(BaseModel):
    """A decision the run needs from the user, offered as clickable options.

    Unlike ``InterruptEvent``, this never pauses a LangGraph run via
    ``interrupt()`` -- the clarify step already ends its own turn
    deterministically (see ``PLAN_BY_INTENT["clarify"]``) and simply waits
    for the user's *next* message, which
    ``planner._try_resolve_pending_clarification`` resolves against these
    same options. This event only tells the client to render the options as
    a card instead of leaving the user to retype one of the two Turkish
    labels verbatim.

    ``question``/``options``/``allow_free_text`` are the original
    single-question fields, kept as a populated mirror of ``questions[0]``
    for backward compatibility; new clients should read ``questions``.
    """

    event: Literal["question"] = "question"
    node: str
    question: str
    options: list[QuestionOption] = Field(default_factory=list)
    #: Whether a free-text reply (not one of ``options``) can also resolve
    #: this question. Always True today -- every clarify question is also
    #: resolvable by echoing a label back, per
    #: ``_try_resolve_pending_clarification`` -- kept explicit so the client
    #: never has to assume it.
    allow_free_text: bool = True
    questions: list[PromptQuestion] = Field(default_factory=list)
    seq: Optional[int] = None


class FinalResultEvent(BaseModel):
    event: Literal["final_result"] = "final_result"
    reply: str
    workflow_status: str
    details: dict[str, Any] = Field(default_factory=dict)
    seq: Optional[int] = None


class ErrorEvent(BaseModel):
    event: Literal["error"] = "error"
    message: str
    details: Any = None
    seq: Optional[int] = None


#: Every event name the backend can put on an SSE stream. Kept as a frozen set
#: (not derived from the model classes' Literal defaults via reflection) so a
#: model rename can't silently change this without the contract test noticing.
WORKFLOW_EVENT_NAMES: frozenset[str] = frozenset(
    {
        "session",
        "node_start",
        "node_end",
        "node_error",
        "node_skipped",
        "token",
        "tool_call",
        "partial_result",
        "planning_completed",
        "guardrail",
        "interrupt",
        "notice",
        "question",
        "final_result",
        "error",
    }
)

__all__ = [
    "SessionEvent",
    "NodeStartEvent",
    "NodeEndEvent",
    "NodeErrorEvent",
    "NodeSkippedEvent",
    "TokenEvent",
    "ToolCallEvent",
    "PartialResultEvent",
    "GuardrailEvent",
    "NoticeEvent",
    "QuestionOption",
    "PromptQuestion",
    "QuestionEvent",
    "PlanningCompletedEvent",
    "InterruptEvent",
    "FinalResultEvent",
    "ErrorEvent",
    "WORKFLOW_EVENT_NAMES",
]
