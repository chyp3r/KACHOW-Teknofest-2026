from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class RunModel(Base, TimestampMixin):
    """One planning-graph invocation (one chat turn) and the decision that
    shaped it.

    Prometheus (``app.observability.ai_metrics``) answers "how is the system
    doing in aggregate"; this answers "what happened on this specific
    request" -- the question that actually comes up when a user reports a
    bad answer ("what did it decide, and why"). ``intent``/``source``/
    ``confidence``/``evidence``/``alternatives``/``clarification`` are every
    field of the ``PlanDecision`` the router resolved for this turn (see
    ``app.ai.workflows.planner.PlanDecision``) -- nothing computed twice,
    just persisted where it can outlive the request.

    Does not replace Langfuse tracing (``app.observability.tracer``), which
    is optional and captures LLM-call-level spans; this is the product's own
    audit trail, always on, and queryable without a third-party account.
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: NOT NULL since migration `0016_recorder_tables_rls` -- written from
    #: `PlanningState.company_id` (see `app.observability.run_recorder.
    #: start_run`), threaded through the planning graph's state alongside
    #: `user_id`. Under row-level security (that same migration).
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    thread_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    document_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    input_text: Mapped[str] = mapped_column(String, nullable=False, default="")
    intent: Mapped[str] = mapped_column(String, nullable=False)
    plan_steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    alternatives: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    clarification: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    #: "running" | "completed" | "failed". Stays "running" for a run that
    #: paused at the human-in-the-loop gate and was never resumed -- an
    #: honest reflection of an abandoned run, not swept or timed out here.
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")


class RunStepModel(Base, TimestampMixin):
    """One plan step's outcome within a run (see ``RunModel``).

    One row per ``STEP_RUNNERS`` dispatch in
    ``app.ai.workflows.planning_graph._execute_one_step`` -- the same
    ``status``/duration this codebase already turns into a Prometheus
    observation (``NODE_DURATION``), just also kept per-run rather than only
    aggregated.
    """

    __tablename__ = "run_steps"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: Denormalized from the parent run; NOT NULL since `0016_recorder_
    #: tables_rls` -- see `RunModel.company_id`.
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("runs.id"), nullable=False, index=True
    )
    step: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
