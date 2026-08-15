from typing import Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class TrainingSampleModel(Base, TimestampMixin):
    """One derived preference-pair sample, persisted so the data an admin
    sees (`GET /companies/{id}/training-samples`) and the data a training
    run actually reads are provably the same rows (Faz C3, #187).

    `source` is `"explicit_feedback"` today -- compiled from `feedback`
    votes whose rated text could be resolved back to a `drafts` row (see
    `app.ai.training.dataset.compile_pairs_from_feedback`). `"hitl_
    rejection"` / `"hitl_revision"` / `"gate_approval"` (implicit signal
    from the HITL approve/reject/revise trail the plan calls out) are
    reserved values, not yet produced -- see #187's body for why: `drafts.
    status` today records workflow outcome (`COMPLETED`/`FAILED`/
    `INTERRUPTED`), not a user accept/reject decision, so deriving a
    preference label from it without a dedicated decision field would
    silently mislabel data. `target_kind`-shaped looseness on this column
    mirrors `FeedbackModel.target_kind`.

    `chosen`/`rejected` are single-wing by construction for the only source
    implemented so far: one feedback vote is one side of a pair (a 👍 is a
    `chosen`-only row, a 👎 is `rejected`-only), never both -- see the class
    docstring on `PreferencePair` for the full reasoning.
    """

    __tablename__ = "training_samples"
    __table_args__ = (
        UniqueConstraint("company_id", "pair_hash", name="uq_training_samples_company_pair_hash"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    #: Which compile-and-mine run last produced/refreshed this row, if any
    #: -- nullable since compiling (`POST .../training-samples/compile`) is
    #: a step an admin can run independently of actually training.
    training_run_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("training_runs.id"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: Loose references back to the raw row this was derived from -- same
    #: looseness as `FeedbackModel.draft_id`, traceability only, no FK.
    source_feedback_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    source_draft_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    prompt_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chosen: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejected: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    #: Identity a re-compile upserts onto -- see `app.ai.training.dataset`
    #: for how this is derived; keeps re-running the compiler idempotent.
    pair_hash: Mapped[str] = mapped_column(String, nullable=False)
    #: `list[str]` of `training_runs.id` that have consumed this sample.
    used_in_runs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
