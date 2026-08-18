"""Best-effort persistence of guardrail decisions (see ``GuardrailEventModel``).

Sibling to ``app.observability.run_recorder``: same short-lived-session
pattern (nodes are plain closures with no request-scoped ``AsyncSession``),
same "never let recording break the actual request" swallow-and-log
contract, and reuses ``settings.RUN_RECORDING_ENABLED`` rather than adding a
second flag -- a guardrail event is the same kind of audit record as a run,
just for a different decision.
"""

import logging
from typing import Optional
from uuid import uuid4

from app.core.config import settings
from app.infrastructure.database.session import tenant_session
from app.observability import company_metrics
from app.observability.ai_metrics import GUARDRAIL_DECISIONS
from app.observability.model.guardrail_model import GuardrailEventModel

logger = logging.getLogger(__name__)


async def record_event(
    *,
    stage: str,
    kind: str,
    decision: str,
    confidence: float = 1.0,
    reasons: Optional[list[str]] = None,
    run_id: Optional[str] = None,
    document_id: Optional[str] = None,
    company_id: Optional[str] = None,
    requester_user_id: Optional[str] = None,
    requester_role: Optional[str] = None,
    effective_clearance: Optional[str] = None,
    related_document_ids: Optional[list[str]] = None,
    llm_model_version: Optional[str] = None,
    prompt_template_version: Optional[str] = None,
) -> None:
    """Record one guardrail decision.

    Args:
        stage: "input" or "output".
        kind: "pii" | "sensitivity" | "injection" | "magic_byte" |
            "archive_bomb" | "groundedness" | "leakage" | "llm_judge" |
            "relevance" (see ``app.ai.workflows.relevance``).
        decision: "passed" | "flagged" | "blocked" | "redacted" |
            "needs_review".
        confidence: 0-1 confidence in the decision.
        reasons: Short human-readable reasons -- never the raw sensitive
            value that triggered the decision (see
            ``app.ai.guardrails.pii.PiiFinding``, which carries only a
            masked preview for exactly this reason).
        run_id: The planning-graph run this decision belongs to, when there
            is one (an upload-time finding has none yet).
        document_id: The document this decision concerns, when there is one.
        company_id: The tenant this decision concerns -- threaded through
            from every call site, including graph-internal ones (see
            ``PlanningState.company_id``). ``None`` only for a genuinely
            unresolvable case; the write below degrades to "not recorded"
            rather than raising, same as any other recorder failure.
        requester_user_id, requester_role, effective_clearance: Who was
            asking, and at what clearance -- populated once the RBAC layer
            (Phase 4) has a real requester to attribute the decision to;
            ``None`` in the open demo/dev path, matching
            ``DocumentModel.owner_id``'s same nullable-until-auth pattern.
        related_document_ids: Every document a response drew on this turn.
        llm_model_version, prompt_template_version: Which model tag and
            template revision produced this decision, when an LLM-judge
            layer (Phase 3) was involved.
    """
    # Unconditional, unlike the DB write below: a Prometheus counter is
    # metrics, not an audit record, and should stay live even when a
    # deployment turns RUN_RECORDING_ENABLED off to skip the DB write.
    GUARDRAIL_DECISIONS.labels(stage=stage, kind=kind, decision=decision).inc()
    if decision == "blocked" and company_id is not None:
        slug = company_metrics.cached_slug(company_id)
        if slug is not None:
            company_metrics.note_guardrail_block(slug, kind)

    if not settings.RUN_RECORDING_ENABLED:
        return
    try:
        async with tenant_session(company_id) as session:
            session.add(
                GuardrailEventModel(
                    id=uuid4().hex,
                    run_id=run_id,
                    document_id=document_id,
                    company_id=company_id,
                    stage=stage,
                    kind=kind,
                    decision=decision,
                    confidence=confidence,
                    reasons=list(reasons or []),
                    requester_user_id=requester_user_id,
                    requester_role=requester_role,
                    effective_clearance=effective_clearance,
                    related_document_ids=list(related_document_ids or []),
                    llm_model_version=llm_model_version,
                    prompt_template_version=prompt_template_version,
                )
            )
            await session.commit()
    except Exception:
        logger.exception(
            "Failed to record guardrail event (stage=%s kind=%s document=%s)",
            stage,
            kind,
            document_id,
        )
