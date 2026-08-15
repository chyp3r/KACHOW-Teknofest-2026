from typing import Optional

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class FeedbackModel(Base, TimestampMixin):
    """One user's 👍/👎 on one piece of AI-generated output.

    This is the raw signal Faz C's later phases (not part of this migration)
    read from: a runtime style adapter (per-company, C2) and an offline
    preference-pair dataset for training (C3) are both derived from rows
    here plus the HITL approve/reject/revise trail already recorded on
    `drafts` -- nothing about training reads this table directly today,
    which is deliberate: "only automatic data *collection* runs for now"
    (see #183/#179's own framing of Faz C).

    Voting again on the *same* text re-votes rather than duplicating: the
    uniqueness constraint is on `(company_id, user_id, target_kind,
    content_hash)`, not on any message/draft id, since a live chat reply
    has no durable id yet at the moment it is shown (`chat_recorder`
    persists it asynchronously after the turn) -- `content_hash` is the one
    identity that is always available immediately. `message_id`/`draft_id`
    are attached best-effort, when the frontend already has them (e.g. a
    vote cast against a message loaded from history), for traceability
    only.

    No raw rated text is stored here (only its hash) -- the actual content
    is already durable elsewhere (`chat_messages.content`, `drafts.content`)
    and duplicating it here would be a second unencrypted copy of whatever
    a document's contents (documents can be sensitivity-marked, see
    `SensitivityLevel`) ended up in a generated reply, same rationale as
    `app.ai.guardrails.pii.PiiFinding` never carrying a raw value.
    """

    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "user_id", "target_kind", "content_hash", name="uq_feedback_vote_identity"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("chat_sessions.id"), nullable=True, index=True
    )
    #: Best-effort link to the specific `chat_messages` row, when the
    #: frontend already had a durable id for it. See the class docstring for
    #: why this is never the identity a vote is deduplicated on.
    message_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("chat_messages.id"), nullable=True, index=True
    )
    #: Loose reference to `drafts.id` -- no FK, same looseness as
    #: `DraftModel.document_id`: a live reply has no drafts row yet either
    #: (`draft_recorder` also persists after the turn), so this is filled in
    #: only when the frontend happens to have it (e.g. from a reloaded
    #: session's persisted message details).
    draft_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    #: "draft" | "revision" | "assist_reply" | "routing" -- not enforced as
    #: a closed set (mirrors `NotificationModel.type`'s looseness), so a new
    #: rateable surface needs no migration.
    target_kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: "like" | "dislike".
    signal: Mapped[str] = mapped_column(String, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Optional structured tags, e.g. `{"uslup": true, "dogruluk": false}` --
    #: which dimension of quality the vote is actually about. Free-form JSON,
    #: not a fixed column set, since the dimension list is a product/UX
    #: decision the backend shouldn't need a migration to change.
    dimensions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    #: sha256 of the rated text -- the vote's real identity (see class
    #: docstring), never the text itself.
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    #: A point-in-time snapshot of context useful for later training-data
    #: derivation without re-joining every table it came from, e.g.
    #: `{"correspondence_type": ..., "confidence_score": ..., "applied_rules": [...]}`.
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
