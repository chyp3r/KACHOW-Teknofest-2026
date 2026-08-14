"""Best-effort persistence of each generated/revised draft.

Same reasoning as `app.observability.run_recorder` and
`app.domains.chat.chat_recorder`: both call sites -- the stateless
`/documents/draft` endpoint's request-scoped handler, and `ChatService`'s
turn-completion hook -- are simpler to keep on one write path than to give
each its own session-management story, and `ChatService` in particular runs
outside a request-scoped `Depends(get_db)` session during SSE streaming (see
`chat_recorder`'s own docstring). So this opens and closes its own
short-lived session per call, the same as those two.

Every function swallows its own exceptions and only logs -- recording a
draft must never be the reason draft generation fails.
"""

import logging
from typing import Optional

from app.core.config import settings
from app.domains.drafts.repository import DraftRepository
from app.infrastructure.database.session import tenant_session

logger = logging.getLogger(__name__)


async def record_draft(
    *,
    user_id: Optional[str],
    session_id: Optional[str],
    document_id: Optional[str],
    content: str,
    correspondence_type: Optional[str] = None,
    destination: Optional[str] = None,
    status: Optional[str] = None,
    confidence_score: Optional[float] = None,
    requires_human_approval: Optional[bool] = None,
    attempts: Optional[int] = None,
    verification: Optional[dict] = None,
    judge: Optional[dict] = None,
    missing_information: Optional[list] = None,
    instructions: Optional[str] = None,
    company_id: Optional[str] = None,
) -> Optional[str]:
    """Append a new draft version and return its id, or `None` if not recorded.

    When `session_id` is given, chains onto that session's latest version
    (a revision); when it is `None` (a direct `/documents/draft` call with
    no chat session), always starts a fresh version=1 draft, since there is
    no key to find a prior version against.

    Args:
        company_id: The caller's tenant -- from `DraftService.
            generate_draft_and_route`'s own `company_id` parameter on the
            direct-API path, or `PlanningState.company_id` via
            `ChatService._maybe_record_draft` on the chat path. Threaded
            through so this write passes `drafts`' row-level-security
            `WITH CHECK` once that table is migrated to it.

    Returns:
        The new draft's id, or `None` when history recording is disabled or
        the write failed -- callers should tolerate an unpopulated
        `draft_id` rather than treat this as fatal.
    """
    if not settings.DRAFT_HISTORY_ENABLED:
        return None
    try:
        async with tenant_session(company_id) as session:
            repository = DraftRepository(session)
            parent = (
                await repository.get_latest_for_session(session_id)
                if session_id is not None
                else None
            )
            draft = await repository.create_version(
                user_id=user_id,
                company_id=company_id,
                session_id=session_id,
                document_id=document_id,
                content=content,
                parent=parent,
                correspondence_type=correspondence_type,
                destination=destination,
                status=status,
                confidence_score=confidence_score,
                requires_human_approval=requires_human_approval,
                attempts=attempts,
                verification=verification,
                judge=judge,
                missing_information=missing_information,
                instructions=instructions,
            )
            await session.commit()
            return draft.id
    except Exception:
        logger.exception("Failed to record draft for session %s", session_id)
        return None
