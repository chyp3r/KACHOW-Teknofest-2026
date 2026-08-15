from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class TrainingRunModel(Base, TimestampMixin):
    """One execution of the training pipeline for one company.

    Faz C3 (#187) only ever produces `kind="style_adapter"` rows today --
    the deterministic-diff + single-LLM-call path that updates
    `app.domains.companies.provider.set_company_adapter`'s `CompanyAdapter`.
    `kind` stays a loose string (not an enum) so `"lora_sft"`/`"lora_dpo"`
    (a future, GPU-backed phase, deliberately out of scope here -- see
    #187's own body) can be added without a migration, same convention as
    `FeedbackModel.target_kind`.

    `artifact_path` is likewise unused by every run this phase produces (a
    style adapter lives in `CompanyModel.settings`, not a file) but is kept
    on the table now so the LoRA phase does not need a schema change later.
    """

    __tablename__ = "training_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    #: "style_adapter" today; "lora_sft" / "lora_dpo" reserved for later.
    kind: Mapped[str] = mapped_column(String, nullable=False)
    #: "queued" | "running" | "succeeded" | "failed" | "skipped" -- "skipped"
    #: is the below-`MIN_FEEDBACK_SAMPLES` outcome, not an error.
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    triggered_by: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    #: "manual" today; "scheduled" reserved for a future cron trigger.
    trigger: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    sample_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: e.g. `{"liked_count": ..., "disliked_count": ..., "adapter_version": ...}`.
    metrics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    artifact_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
