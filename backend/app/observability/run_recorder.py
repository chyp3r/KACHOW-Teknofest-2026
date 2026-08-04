"""Best-effort persistence of each planning-graph run's decision trail.

The planning graph is compiled once per process (see
``app.api.dependency.get_planning_graph``) and its nodes are plain closures
-- they never get a request-scoped ``AsyncSession`` the way a FastAPI
endpoint does via ``Depends(get_db)``. Each function here opens and closes
its own short-lived session instead, the same pattern already used for a
one-off connectivity check (``app.infrastructure.database.session.
verify_db_connection``).

Every function swallows its own exceptions and only logs -- recording a run
must never be the reason a chat turn fails. This mirrors how Langfuse
tracing (``app.observability.tracer``) and every other secondary side effect
in this codebase (event bus publishes, the document ownership registry)
degrade to "not recorded" rather than raising.
"""

import logging
from typing import Any, Optional
from uuid import uuid4

from app.core.config import settings
from app.infrastructure.database.session import AsyncSessionLocal
from app.observability.model.run_model import RunModel, RunStepModel

logger = logging.getLogger(__name__)


async def start_run(
    *,
    run_id: str,
    thread_id: str,
    user_id: Optional[str],
    document_id: Optional[str],
    input_text: str,
    intent: str,
    plan_steps: list[str],
    source: str,
    confidence: float,
    evidence: tuple[str, ...],
    alternatives: tuple[tuple[str, float], ...],
    clarification: Optional[dict[str, Any]],
) -> None:
    """Record a run's resolved plan at the moment planning completes.

    Args:
        run_id: This turn's run id (see ``PlanningState.run_id``).
        thread_id: The checkpointer thread this run belongs to.
        user_id: The authenticated caller, when known.
        document_id: The attached document, if any.
        input_text: The user's message this turn.
        intent, plan_steps, source, confidence, evidence, alternatives,
            clarification: Every field of the ``PlanDecision``
            ``resolve_plan`` produced (see
            ``app.ai.workflows.planner.PlanDecision``).
    """
    if not settings.RUN_RECORDING_ENABLED:
        return
    try:
        async with AsyncSessionLocal() as session:
            session.add(
                RunModel(
                    id=run_id,
                    thread_id=thread_id,
                    user_id=user_id,
                    document_id=document_id,
                    input_text=input_text,
                    intent=intent,
                    plan_steps=list(plan_steps),
                    source=source,
                    confidence=confidence,
                    evidence=list(evidence),
                    alternatives=[list(item) for item in alternatives],
                    clarification=clarification,
                    status="running",
                )
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to record run start for %s", run_id)


async def record_step(
    *,
    run_id: str,
    step: str,
    status: str,
    duration_ms: float,
    error: Optional[str] = None,
) -> None:
    """Record one plan step's outcome (see ``_execute_one_step``).

    A no-op when ``run_id`` is empty -- a resumed run whose checkpoint
    predates this field (or any state built without going through
    ``planning_node``) has nothing to attach the step to.
    """
    if not settings.RUN_RECORDING_ENABLED or not run_id:
        return
    try:
        async with AsyncSessionLocal() as session:
            session.add(
                RunStepModel(
                    id=uuid4().hex,
                    run_id=run_id,
                    step=step,
                    status=status,
                    duration_ms=duration_ms,
                    error=error,
                )
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to record run step '%s' for run %s", step, run_id)


async def end_run(*, run_id: str, status: str) -> None:
    """Close out a run's status once its terminal node runs.

    A no-op when ``run_id`` is empty, same reasoning as :func:`record_step`.
    Never fires for a run that paused at the human-in-the-loop gate and was
    never resumed -- it stays "running", an honest reflection of an
    abandoned run rather than a swept or timed-out one.
    """
    if not settings.RUN_RECORDING_ENABLED or not run_id:
        return
    try:
        async with AsyncSessionLocal() as session:
            run = await session.get(RunModel, run_id)
            if run is None:
                return
            run.status = status
            await session.commit()
    except Exception:
        logger.exception("Failed to record run end for %s", run_id)
