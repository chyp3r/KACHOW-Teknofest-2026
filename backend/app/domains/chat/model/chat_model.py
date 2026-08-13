from typing import Optional

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class ChatSessionModel(Base, TimestampMixin):
    """One chat conversation, keyed by its LangGraph checkpointer thread_id.

    ``id`` stores the *composed* thread_id (``ChatService._thread_id``,
    ``f"{user_id}:{session_id}"`` when authenticated) rather than the raw
    client-supplied session_id, so a session row joins ``RunModel.thread_id``
    on the same string. This table exists purely to answer "what has this
    user talked about" (listing + display); the LangGraph checkpointer
    remains the source of truth for resuming a paused workflow.
    """

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: Nullable for now -- see `DraftModel.company_id`'s docstring: this
    #: recorder is invoked from `ChatService`'s turn-completion hook, which
    #: does not yet carry `company_id` through its state. Populated once
    #: Faz 3 threads it through, same as `user_id` already is today.
    company_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("companies.id"), nullable=True, index=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    document_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    #: First user message, truncated -- a cheap display label, not derived
    #: from an LLM call.
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class ChatMessageModel(Base, TimestampMixin):
    """One turn's worth of message (either side) within a `ChatSessionModel`.

    Written by ``app.domains.chat.chat_recorder`` after a turn completes --
    never from the request-scoped DI path, since the SSE streaming endpoint's
    worker task outlives the FastAPI dependency-injected session (see the
    recorder module's own docstring).
    """

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: Denormalized from the parent session; nullable for now -- see
    #: `ChatSessionModel.company_id`.
    company_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("companies.id"), nullable=True, index=True
    )
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("chat_sessions.id"), nullable=False, index=True
    )
    #: "user" | "assistant"
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    workflow_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: The assistant turn's ``ChatMessageResponse.details`` payload; unset
    #: for user turns.
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
