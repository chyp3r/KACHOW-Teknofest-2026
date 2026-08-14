import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_auth_if_enabled
from app.api.responses import SuccessResponse
from app.domains.notifications.repository import NotificationRepository
from app.domains.notifications.schema.notification_schema import NotificationResponse
from app.domains.notifications.service import NotificationService, channel_for
from app.domains.users.model.user_model import UserModel
from app.infrastructure.cache import get_cache
from app.infrastructure.database.session import get_db
from app.shared.dto.pagination import PaginatedResponse, PaginationParam

logger = logging.getLogger(__name__)

# Authentication is mandatory (see require_auth_if_enabled) -- every route in
# this router carries a real, tenant-bound current_user.
router = APIRouter(
    prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth_if_enabled)]
)


def _service(db: AsyncSession) -> NotificationService:
    return NotificationService(NotificationRepository(db), cache=get_cache())


@router.get("", response_model=None)
async def list_notifications(
    unread_only: bool = False,
    pagination: PaginationParam = Depends(),
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """The caller's own notifications, newest first."""
    service = _service(db)
    items, total = await service.list_for_user(
        current_user.company_id,
        current_user.id,
        unread_only=unread_only,
        skip=pagination.offset,
        limit=pagination.limit,
    )
    page_items = [
        NotificationResponse.model_validate(item).model_dump(mode="json") for item in items
    ]
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0
    return SuccessResponse(
        data=PaginatedResponse(
            items=page_items, total=total, page=pagination.page, size=pagination.size, pages=pages
        ).model_dump()
    )


@router.post("/{notification_id}/read", response_model=None)
async def read_notification(
    notification_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Mark one notification as read."""
    service = _service(db)
    notification = await service.mark_read(notification_id, current_user.company_id, current_user.id)
    return SuccessResponse(data=NotificationResponse.model_validate(notification).model_dump(mode="json"))


@router.post("/read-all", response_model=None)
async def read_all_notifications(
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Mark every unread notification of the caller as read."""
    service = _service(db)
    count = await service.mark_all_read(current_user.company_id, current_user.id)
    return SuccessResponse(data={"marked_read": count})


#: How long a single `get_message` poll blocks before the loop re-checks for
#: client disconnect and sends a keep-alive comment -- long enough to not
#: busy-loop, short enough that a dropped connection is noticed promptly and
#: an idle proxy connection doesn't time out (mirrors `chat/router.py`'s own
#: disconnect-polling cadence, just event-driven instead of generator-driven).
_POLL_TIMEOUT_SECONDS = 20.0


@router.get("/stream")
async def stream_notifications(
    http_request: Request,
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Live-push notification stream over SSE.

    Backed by Redis pub/sub (`RedisCache.publish`/`NotificationService.
    create`), not the process-wide in-memory `EventBus` alone -- a multi-
    worker uvicorn deployment would otherwise drop any notification
    published from a worker other than the one holding this connection (see
    the tenancy plan's own risk note on this). A dropped or never-received
    live push is never data loss: the notification row already exists by
    the time it's published (see `NotificationService.create`), so
    `GET /notifications` always has it regardless of whether this stream
    was even connected.
    """
    cache = get_cache()
    await cache.connect()
    channel = channel_for(current_user.company_id, current_user.id)
    pubsub = cache.client.pubsub()
    await pubsub.subscribe(channel)

    async def event_generator():
        try:
            yield 'data: {"event": "connected"}\n\n'
            while True:
                if await http_request.is_disconnected():
                    logger.info("Client disconnected; closing notification stream.")
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=_POLL_TIMEOUT_SECONDS
                )
                if message is None:
                    yield ": keep-alive\n\n"
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield f"data: {data}\n\n"
        except Exception:
            logger.exception("Notification stream failed")
            error = json.dumps(
                {"event": "error", "message": "Bildirim akışı sırasında bir hata oluştu."},
                ensure_ascii=False,
            )
            yield f"data: {error}\n\n"
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
