from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class ConversationParticipantModel(Base, TimestampMixin):
    """One user's membership in one conversation -- this row IS the access grant.

    `role_in_conversation` is `"owner"` (the group's creator, or anyone
    later promoted -- meaningless for a DM, where both sides are equal) or
    `"member"`, open string like `units.role_in_unit`.

    `left_at` is a soft-leave: a former participant keeps read access to
    the history that already existed while they were in the conversation
    (their row is still there, just marked left), but may not send new
    messages and stops appearing in `list_for_conversation`'s "who's
    active" view. There is no hard delete of this row -- re-joining after
    leaving a group would otherwise either resurrect a stale row with a
    confusing history or collide with `uq_conversation_participants_conv_user`.

    `last_read_message_id` is a loose pointer (no FK -- a message can be
    soft-deleted out from under it) used only to compute an unread count by
    comparing timestamps against the pointed-to message's `created_at`
    (message ids are opaque uuid-hex, not ordered, so "unread since" can't
    compare ids directly). `created_at` (from `TimestampMixin`) already
    doubles as "joined at" -- no separate column for it.
    """

    __tablename__ = "conversation_participants"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "user_id", name="uq_conversation_participants_conv_user"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    role_in_conversation: Mapped[str] = mapped_column(String, nullable=False, default="member")
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_read_message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    muted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
