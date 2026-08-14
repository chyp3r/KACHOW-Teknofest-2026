from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class DraftShareModel(Base, TimestampMixin):
    """One draft version sent from one user to another (the şartname's
    "çalışanlar arası taslak gönder/al" -- employee-to-employee draft
    delivery).

    Targets a specific ``drafts`` row (a specific version), not a session --
    ``DraftModel`` is already an append-only version chain, and sending
    "the current draft" just means sending its latest row's id at send
    time; nothing here needs to track "did a newer version get sent later",
    that is simply a second, separate share row.

    There is no dedicated inbox/outbox table: "inbox" is
    ``recipient_id = me``, "outbox" is ``sender_id = me``, both against this
    one table (see ``DraftShareRepository.list_inbox``/``list_outbox``).
    """

    __tablename__ = "draft_shares"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    draft_id: Mapped[str] = mapped_column(String, ForeignKey("drafts.id"), nullable=False, index=True)
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    recipient_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    #: The unit ``drafts.destination`` (the AI's routing suggestion at
    #: generation time) resolves to, copied in at send time -- see
    #: ``DraftShareService.send``. `NULL` when ``destination`` doesn't match
    #: any current unit name (renamed/deleted since, or a direct draft with
    #: no routing decision at all); an honest miss, not an error.
    suggested_unit_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("units.id"), nullable=True
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: "sent" | "read" | "accepted" | "rejected" | "withdrawn".
    status: Mapped[str] = mapped_column(String, nullable=False, default="sent")
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    response_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
