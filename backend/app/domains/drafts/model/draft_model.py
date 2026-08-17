from typing import Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class DraftModel(Base, TimestampMixin):
    """One version of a drafted official correspondence.

    A row is written per turn that produces or revises a draft -- never
    overwritten, so `session_id` + `version` reconstructs the full edit
    history and `parent_draft_id` chains a revision back to the version it
    edited. There is no separate "current draft" table: the latest row for a
    `session_id` (by `version`) is the current one (see
    `DraftRepository.get_latest_for_session`).

    `session_id` is nullable and carries no FK: a draft produced through the
    chat flow gets the composed thread_id (see `ChatService._thread_id`),
    but a direct `POST /documents/draft` call has no chat session at all.
    `document_id` is likewise a loose `storage_path`-shaped reference, same
    as `DocumentModel`'s own looseness around ownership.
    """

    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: NOT NULL since migration `0016_recorder_tables_rls` -- populated by
    #: every `draft_recorder.record_draft` call site, including the chat
    #: path via `PlanningState.company_id` (see `RunModel.company_id`'s
    #: docstring).
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    session_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    document_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_draft_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("drafts.id"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    correspondence_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    destination: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: `destination` resolved against `units` at write time (see
    #: `app.domains.drafts.draft_recorder.record_draft`) -- `None` when
    #: `destination` didn't match any unit in this company (renamed/
    #: deleted since, or routing came back empty), same honesty
    #: `draft_shares.suggested_unit_id` already has. This is what a
    #: transfer's cross-unit check and recipient recommendation
    #: (`app.domains.transfers`) read; nothing re-resolves `destination`
    #: by name anymore.
    destination_unit_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("units.id"), nullable=True, index=True
    )
    #: The routing graph's own `RouteOutput.justification` for this
    #: version -- persisted so a transfer confirmation can show "why this
    #: unit" without re-running routing.
    destination_justification: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    requires_human_approval: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    attempts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: The deterministic verifier's report (see `DraftResponseSchema.verification`).
    verification: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    #: The quality judge's structured verdict, when it ran (`DraftResponseSchema.judge`).
    judge: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    #: `List[InfoQuestion]` asked of the user to complete this draft.
    missing_information: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
