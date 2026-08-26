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

# Kimlik doğrulama zorunludur (bkz. require_auth_if_enabled) -- bu router'daki
# her rota gerçek, kiracıya bağlı bir current_user taşır.
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
    """Çağıranın kendi bildirimleri, en yeniden en eskiye."""
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
    """Tek bir bildirimi okundu olarak işaretler."""
    service = _service(db)
    notification = await service.mark_read(notification_id, current_user.company_id, current_user.id)
    return SuccessResponse(data=NotificationResponse.model_validate(notification).model_dump(mode="json"))


@router.post("/read-all", response_model=None)
async def read_all_notifications(
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Çağıranın okunmamış tüm bildirimlerini okundu olarak işaretler."""
    service = _service(db)
    count = await service.mark_all_read(current_user.company_id, current_user.id)
    return SuccessResponse(data={"marked_read": count})


#: Döngünün istemci bağlantısının kesilip kesilmediğini yeniden kontrol edip
#: bir keep-alive yorumu göndermeden önce tek bir `get_message` sorgulamasının
#: ne kadar bloke olacağı -- meşgul döngüye girmeyecek kadar uzun, kopan bir
#: bağlantının hızlıca fark edilmesini ve boşta bekleyen bir proxy bağlantısının
#: zaman aşımına uğramamasını sağlayacak kadar kısa (`chat/router.py`'nin kendi
#: bağlantı kesme sorgulama ritmini yansıtır, sadece generator yerine olay
#: tabanlıdır).
_POLL_TIMEOUT_SECONDS = 20.0


@router.get("/stream")
async def stream_notifications(
    http_request: Request,
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """SSE üzerinden canlı bildirim akışı.

    Süreç geneli bellek içi `EventBus`'ın tek başına değil, Redis pub/sub
    (`RedisCache.publish`/`NotificationService.create`) tarafından
    desteklenir -- aksi halde çok işçili (multi-worker) bir uvicorn
    dağıtımı, bu bağlantıyı tutan işçi dışındaki bir işçiden yayınlanan her
    bildirimi kaybederdi (bkz. kiracılık planının bu konudaki risk notu).
    Kaçırılan veya hiç alınmayan bir canlı bildirim asla veri kaybı değildir:
    bildirim satırı yayınlandığı anda zaten mevcuttur (bkz.
    `NotificationService.create`), bu yüzden bu akış bağlı olsa da olmasa da
    `GET /notifications` her zaman bu bildirime sahiptir.
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
