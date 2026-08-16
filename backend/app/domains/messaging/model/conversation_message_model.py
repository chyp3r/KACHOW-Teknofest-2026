from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class ConversationMessageModel(Base, TimestampMixin):
    """One message in one conversation -- text, artifact, or system.

    A single table, not split by `kind` -- thread ordering must come from
    one table (splitting it would turn every thread read into a UNION over
    time). `kind` is `"text"` (plain human message), `"artifact"` (a taslak/
    evrak transfer notice -- see `artifact_transfer_id`; introduced fully in
    Faz 3), or `"system"` (membership events like "X gruba eklendi").

    `artifact_transfer_id` is a plain nullable String, not yet a foreign
    key -- `artifact_transfers` (Faz 3, migration `0024`) does not exist at
    this point in the migration chain; the FK is added once both tables do.
    An artifact message's card content (title, version, sender, status) is
    never cached into `body` -- the frontend reads it live from the
    transfer row, so a withdrawn/failed transfer's card reflects reality
    instead of a stale snapshot.

    `sender_id` is nullable only for a future system-authored row (`kind=
    "system"`); every `"text"`/`"artifact"` message has a real sender.
    """

    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conversation_messages_conv_created", "conversation_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False, index=True
    )
    sender_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="text")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    artifact_transfer_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
