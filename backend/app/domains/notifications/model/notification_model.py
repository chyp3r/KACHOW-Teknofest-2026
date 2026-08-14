from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class NotificationModel(Base, TimestampMixin):
    """One in-app notification for one user.

    Always the durable half of a notification: `app.events.subscribers`
    writes a row here *before* it publishes to Redis for the live SSE push
    (`app.domains.notifications.router`'s `/stream`), so a dropped Redis
    message or a disconnected client never loses the notification itself --
    it is simply picked up on the next `GET /notifications` poll instead of
    arriving live. Purely personal: unlike documents/drafts/pools there is
    no `bypasses_ownership` company-wide view here, a notification only
    ever belongs to the one `user_id` it was written for.
    """

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    #: e.g. "draft_shared" | "draft_share_responded" -- a short machine tag,
    #: not enforced as a closed set (mirrors `document_pool_items.source`'s
    #: looseness) so a future notification type needs no migration.
    type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: What the notification is about, e.g. `resource_type="draft_share"`,
    #: `resource_id=<draft_shares.id>` -- loose, not a FK, since
    #: `resource_type` varies by `type`.
    resource_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
