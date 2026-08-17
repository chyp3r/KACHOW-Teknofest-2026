from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class ArtifactTransferModel(Base, TimestampMixin):
    """One artifact (taslak/evrak) transfer, from any channel.

    The single record every transfer path -- manual chat send, the legacy
    `POST /drafts/{id}/send` REST endpoint, and (Faz 4) the AI-assisted
    flow -- writes exactly one row into, via `ArtifactTransferService.
    execute`. This is deliberately *not* a replacement for the tamper-
    evident `audit_log` hash chain (`app.domains.audit`) -- that is written
    separately, best-effort, after commit. This table is the queryable
    domain record: "who sent what to whom, through which channel, with
    what outcome" answered in one row, one query.

    `source_artifact_id` is a loose reference (a `drafts.id` or a
    `documents.id`/storage_path), same looseness `drafts.document_id`
    already has -- `artifact_kind` disambiguates which table it points
    into. `snapshot_ref` is the recipient's own copy: a new `drafts.id`
    (forked at transfer time) for a draft, or the new `document_pool_items.
    id` for a document.
    """

    __tablename__ = "artifact_transfers"
    __table_args__ = (
        #: Partial unique index, not a `UniqueConstraint` -- same reasoning
        #: as `ConversationModel.dm_key`'s own index: most transfers don't
        #: supply an idempotency key at all, and NULL-vs-NULL must never
        #: collide.
        Index(
            "uq_artifact_transfers_idempotency",
            "company_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    #: "draft" | "document"
    artifact_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_artifact_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: The draft version transferred, when `artifact_kind == "draft"` --
    #: pinned at transfer time so a later revision of the same draft never
    #: silently changes what this row claims was sent.
    source_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    snapshot_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    recipient_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    conversation_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=True
    )
    message_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("conversation_messages.id"), nullable=True
    )
    #: "chat" | "ai" | "rest"
    channel: Mapped[str] = mapped_column(String, nullable=False)
    #: True only for a Faz 4 AI-suggested recipient the user then confirmed
    #: -- never set by this phase's manual channels.
    ai_suggested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: "routing_unit" | "favorite_rank" | "explicit_name" -- Faz 4 only.
    recommendation_source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    recommendation_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    #: Whether the recipient's primary unit differs from the artifact's own
    #: `destination_unit_id` -- computed once here by `TransferPolicy`,
    #: never left for a caller (LLM included) to judge for itself.
    cross_unit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: False only ever for a future automated/system-initiated transfer --
    #: every channel this phase supports requires the acting user's own
    #: HTTP call, which is itself the confirmation.
    confirmed_by_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: "permit" | "deny" -- the policy verdict this transfer executed
    #: under. A row only ever exists for "permit"; a "deny" never reaches
    #: persistence (see `ArtifactTransferService.execute`), so this column
    #: is always "permit" today, kept for the Faz 4 audit trail shape where
    #: a denied attempt may still be worth recording.
    policy_decision: Mapped[str] = mapped_column(String, nullable=False, default="permit")
    policy_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: "executed" | "failed" | "withdrawn"
    status: Mapped[str] = mapped_column(String, nullable=False, default="executed")
    #: Caller-supplied idempotency token. `None` for most manual sends;
    #: required by the Faz 4 AI channel (`f"intent:{intent_id}"`) so a
    #: retried confirmation never re-executes.
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
