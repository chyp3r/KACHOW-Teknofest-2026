from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class ArtifactTransferIntentModel(Base, TimestampMixin):
    """The AI channel's confirmation lifecycle for one proposed transfer.

    **Not read or written anywhere yet.** Migrated now (Faz 3, #199) so its
    RLS policy and table shape ship alongside `artifact_transfers`, but the
    state machine that owns it -- `TransferIntentService`, the CAS-based
    `state` transitions, `transfer_gate_node`'s `interrupt()` -- is Faz 4.
    Existing here, unused, is deliberately safe: RLS is already enforced,
    and there is nothing to migrate later beyond adding the reader/writer
    code.

    `state` will carry the lifecycle documented in the plan's §I:
    INTENT_DETECTED -> {AMBIGUOUS, RECIPIENT_RESOLVED, UNRESOLVED} ->
    POLICY_CHECKED -> {AWAITING_CONFIRMATION, POLICY_DENIED} ->
    {CONFIRMED, CANCELLED} -> {TRANSFER_EXECUTED, FAILED}. Advanced via a
    single conditional `UPDATE ... WHERE state = :expected` (row-level CAS)
    so a duplicate or stale confirmation resolves to "0 rows changed"
    rather than a race.
    """

    __tablename__ = "artifact_transfer_intents"
    __table_args__ = (
        #: Composite, not a plain single-column index on `thread_id` --
        #: every real query here is "this thread's active intent(s)",
        #: which is `(thread_id, state)`; Postgres can still serve a
        #: thread_id-only lookup off the same index's leading column.
        Index("ix_artifact_transfer_intents_thread_state", "thread_id", "state"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    #: The LangGraph thread this intent belongs to -- same composed id
    #: `ChatService._thread_id` produces.
    thread_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    requested_by: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    artifact_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_artifact_id: Mapped[str] = mapped_column(String, nullable=False)
    source_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolved_recipient_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    #: Candidate list when name resolution was ambiguous (multiple same-
    #: named users) -- rendered verbatim in the disambiguation interrupt,
    #: never re-guessed by the model.
    candidate_recipients: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False)
    policy_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    #: sha256 of `policy_snapshot`, re-computed at confirmation time and
    #: compared -- the TOCTOU guard between "policy was checked" and "user
    #: clicked confirm".
    policy_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    cross_unit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resulting_transfer_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("artifact_transfers.id"), nullable=True
    )
