from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class GuardrailEventModel(Base, TimestampMixin):
    """One input or output guardrail decision, kept for audit.

    Sibling to ``RunModel``/``RunStepModel`` (``app.observability.model.
    run_model``): the same "always-on, first-party audit trail, independent
    of the optional Langfuse tracer" role, for guardrail decisions
    specifically. A user reporting "the assistant told me something it
    shouldn't have" needs an answer to "what did the guardrail see, and what
    did it decide" that outlives the request and doesn't depend on a
    third-party tracing account being configured.

    ``run_id``/``document_id`` are both nullable and independent: an
    upload-time PII/sensitivity finding has a ``document_id`` and no
    ``run_id`` yet (the chat turn that reads it comes later, if ever); an
    output-gate decision on an assist reply has a ``run_id`` and whatever
    ``related_document_ids`` it actually drew on.
    """

    __tablename__ = "guardrail_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: Nullable for now: populated when the caller is request-scoped with
    #: `company_id` already in hand (e.g. `DocumentService`'s upload-time
    #: sensitivity assessment); `NULL` for the guardrail events recorded
    #: from inside the planning graph until Faz 3 threads `company_id`
    #: through `PlanningState` alongside `user_id` (see `RunModel.company_id`).
    company_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("companies.id"), nullable=True, index=True
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("runs.id"), nullable=True, index=True
    )
    document_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    #: "input" | "output".
    stage: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: "pii" | "sensitivity" | "injection" | "magic_byte" | "archive_bomb" |
    #: "groundedness" | "leakage" | "llm_judge".
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: "passed" | "flagged" | "blocked" | "redacted" | "needs_review".
    decision: Mapped[str] = mapped_column(String, nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    #: Short, human-readable reason strings -- never the raw sensitive value
    #: that triggered the decision (see ``app.ai.guardrails.pii.PiiFinding``,
    #: which carries only a redacted preview for this exact reason).
    reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    #: Who was asking, and at what clearance -- the questions an audit of a
    #: leakage-prevention block actually needs answered.
    requester_user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    requester_role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    effective_clearance: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: A response can draw on several documents in one turn; this stays a
    #: list even when only one applies, so the shape never has to change.
    related_document_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: The Ollama model tag actually used for this decision (e.g. from
    #: ``settings.OLLAMA_MODEL``), and which on-disk revision of the prompt
    #: template produced it (``PromptManager``'s per-template version) --
    #: together, "would this decision reproduce today."
    llm_model_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    prompt_template_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
