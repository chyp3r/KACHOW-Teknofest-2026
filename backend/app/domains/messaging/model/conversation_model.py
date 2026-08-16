from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class ConversationModel(Base, TimestampMixin):
    """One DM or group thread between company users.

    `kind` is `"dm"` or `"group"`, open string (same looseness as `units.
    role_in_unit`). `dm_key` is the sorted `"user_a_id:user_b_id"` pair for
    a `kind="dm"` row, `None` for a group -- a partial unique index on
    `(company_id, dm_key) WHERE kind = 'dm'` (see migration `0022_messaging`)
    makes a second DM between the same two users structurally impossible,
    so `ConversationService.open_dm` never has to race a duplicate-check
    against a concurrent open from the other side.

    Access to a conversation is not an ABAC decision -- it is answered by
    whether a `ConversationParticipantModel` row exists for the caller,
    the same "the row itself is the grant" pattern `draft_shares` already
    uses (see `app.domains.drafts.draft_share_service.DraftShareService`'s
    own docstring).
    """

    __tablename__ = "conversations"
    __table_args__ = (
        #: Partial unique index, not a `UniqueConstraint` -- same reasoning
        #: as `uq_unit_memberships_one_primary_per_user`: Postgres has no
        #: declarative "unique except when false" shape, so this is a plain
        #: index scoped by `WHERE kind = 'dm'` instead.
        Index(
            "uq_conversations_dm_key",
            "company_id",
            "dm_key",
            unique=True,
            postgresql_where=text("kind = 'dm'"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    #: Group display name. `None` for a DM -- a DM's "title" is always
    #: derived from its other participant, computed by the service/frontend,
    #: never stored (there is nothing to keep in sync when a username
    #: changes).
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    dm_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    #: Denormalized from the latest `conversation_messages` row, kept in
    #: sync by `ConversationMessageRepository.create` in the same flush --
    #: the conversation list sorts by this without an aggregate join per row.
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
