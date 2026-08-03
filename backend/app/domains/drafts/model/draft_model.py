from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class DraftModel(Base, TimestampMixin):
    """One version of a drafted correspondence.

    A row is written per conversational turn that produces or revises a
    draft -- never overwritten, so `session_id` + `version` reconstructs the
    full edit history and `parent_draft_id` chains a revision back to the
    version it edited. There is no separate "current draft" table: the
    latest row for a `session_id` (by `version`) is the current draft.
    """

    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: Nullable: REQUIRE_AUTH defaults to disabled (see
    #: app.api.dependency.require_auth_if_enabled), so an anonymous session's
    #: drafts carry no user.
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    #: LangGraph checkpointer thread_id (see ChatService._thread_id) -- the
    #: conversation this draft belongs to.
    session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: The source document's storage_path, when one was attached. Not a
    #: foreign key: DocumentModel is an unmigrated skeleton (see
    #: domains/documents/model/document_model.py), so this is the same plain
    #: string identifier every other document reference in the codebase uses.
    document_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_draft_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("drafts.id"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    correspondence_type: Mapped[str | None] = mapped_column(String, nullable=True)
    routed_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    #: StepStatus value (COMPLETED, NEEDS_HUMAN_APPROVAL, ...) as a plain
    #: string -- see app.core.enums.step_status.StepStatus.
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The instruction that produced this version: the original drafting
    #: request for version 1, the revision instruction for later ones.
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
