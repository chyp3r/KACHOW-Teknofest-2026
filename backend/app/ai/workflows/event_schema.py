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
    seq: Optional[int] = None


class InterruptEvent(BaseModel):
    event: Literal["interrupt"] = "interrupt"
    kind: Literal["missing_information", "draft_approval"]
    interrupt_id: str
    payload: dict[str, Any]
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
        "partial_result",
        "planning_completed",
        "interrupt",
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
    "PartialResultEvent",
    "PlanningCompletedEvent",
    "InterruptEvent",
    "FinalResultEvent",
    "ErrorEvent",
    "WORKFLOW_EVENT_NAMES",
]
