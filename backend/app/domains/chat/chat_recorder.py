"""Best-effort persistence of each chat turn's messages.

`ChatService` is invoked both from a normal request (`/chat/message`,
`/chat/resume/sync`) and from the SSE streaming endpoints, where the actual
work happens in a background `asyncio.create_task` consumed by an async
generator (see `ChatService.handle_message_stream`). By the time that task
runs, the FastAPI request handler that owned any `Depends(get_db)` session
has already returned the `StreamingResponse` object and moved on -- so, same
as `app.observability.run_recorder`, this opens and closes its own
short-lived session per call instead of taking an injected one.

Every function swallows its own exceptions and only logs -- recording a
chat turn must never be the reason a chat turn fails.
"""

import logging
from typing import Any, Optional

from app.core.config import settings
from app.domains.chat.repository import ChatMessageRepository, ChatSessionRepository
from app.infrastructure.database.session import tenant_session

logger = logging.getLogger(__name__)


async def record_turn(
    *,
    thread_id: str,
    user_id: Optional[str],
    document_id: Optional[str],
    user_message: str,
    user_details: Optional[dict[str, Any]] = None,
    reply: str,
    workflow_status: str,
    details: Optional[dict[str, Any]] = None,
    company_id: Optional[str] = None,
) -> None:
    """Persist one completed turn: the session row plus both its messages.

    Args:
        thread_id: The composed checkpointer thread_id (see
            `ChatService._thread_id`), reused as `ChatSessionModel.id`.
        user_id: The authenticated caller, when known.
        document_id: The document attached to this turn, if any.
        user_message: The caller's input text this turn.
        user_details: Optional structured metadata stored on the caller's
            message. Resume turns use this to preserve the answered HITL
            form without changing the public request/response contract.
        reply: The assistant's reply text (or the interrupted-turn prompt).
        workflow_status: `ChatMessageResponse.workflow_status` for this turn.
        details: `ChatMessageResponse.details` for this turn, stored on the
            assistant message only.
        company_id: The caller's tenant -- threaded through so this write
            passes `chat_sessions`/`chat_messages`' row-level-security
            `WITH CHECK` once those tables are migrated to it.
    """
    if not settings.CHAT_HISTORY_ENABLED:
        return
    try:
        async with tenant_session(company_id) as session:
            sessions = ChatSessionRepository(session)
            messages = ChatMessageRepository(session)
            await sessions.get_or_create(
                thread_id,
                user_id=user_id,
                company_id=company_id,
                document_id=document_id,
                title=_derive_title(user_message),
            )
            await messages.add_message(
                thread_id,
                role="user",
                content=user_message,
                details=user_details,
                company_id=company_id,
            )
            await messages.add_message(
                thread_id,
                role="assistant",
                content=reply,
                workflow_status=workflow_status,
                details=details,
                company_id=company_id,
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to record chat turn for thread %s", thread_id)


def _derive_title(user_message: str, max_length: int = 80) -> str:
    """A cheap display label for a session list -- no LLM call involved."""
    text = " ".join(user_message.split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"
