import logging
from typing import List, Optional, Tuple
from uuid import uuid4

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.domains.notifications.model.notification_model import NotificationModel
from app.domains.notifications.repository import NotificationRepository
from app.domains.notifications.schema.notification_schema import NotificationResponse
from app.infrastructure.cache.redis import RedisCache

logger = logging.getLogger(__name__)


def channel_for(company_id: str, user_id: str) -> str:
    """Bir kullanıcının canlı bildirim akışının dinlediği Redis pub/sub
    kanalı.

    `NotificationService.create` (yayıncı) ile
    `app.domains.notifications.router`'ın SSE endpoint'i (abone) arasında
    paylaşılır -- `user_id` tek başına zaten global olarak benzersiz
    olmasına rağmen `company_id` kanal adına dahil edilir, salt sapkın
    bir şirketler-arası kanal çakışmasının yalnızca olası değil, yapısal
    olarak imkansız olması için.
    """
    return f"notifications:{company_id}:{user_id}"


class NotificationService:
    """`notifications` için servis -- okuma/yazma artı canlı-push yan
    etkisi.

    Bilinçli olarak `bypasses_ownership` şirket-geneli görünüm yok (bkz.
    `NotificationModel`'in docstring'i): buradaki her metot yalnızca
    çağıranın kendi `user_id`'siyle sınırlıdır, nokta.
    """

    def __init__(self, repository: NotificationRepository, cache: Optional[RedisCache] = None):
        self.repository = repository
        self.cache = cache

    async def create(
        self,
        *,
        company_id: str,
        user_id: str,
        type: str,
        title: str,
        body: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
    ) -> NotificationModel:
        """Bir bildirim satırı yazar, ardından best-effort olarak canlı
        yayınlar.

        Args:
            company_id: Kiracı kapsamı.
            user_id: Bu bildirimin kimin için olduğu.
            type: Kısa bir makine etiketi (bkz. `NotificationModel.type`).
            title: İnsan tarafından okunabilir başlık.
            body: Opsiyonel insan tarafından okunabilir ayrıntı.
            resource_type: Bildirimin ne hakkında olduğu (örn. "draft_share").
            resource_id: İlgili satırın id'si.

        Returns:
            Kalıcı hale getirilmiş `NotificationModel`. DB yazımı her
            zaman gerçekleşir; aşağıdaki Redis yayını bunun üzerine saf
            bir yan etkidir, bu yüzden bir Redis kesintisi bildirimin var
            olmasını hiçbir zaman engellemez -- bu sıralamanın (önce yaz,
            sonra best-effort push) neden bilinçli olduğu için
            `RedisCache.publish`'in kendi docstring'ine bakın.
        """
        notification = await self.repository.create(
            NotificationModel(
                id=uuid4().hex,
                company_id=company_id,
                user_id=user_id,
                type=type,
                title=title,
                body=body,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        )
        if self.cache is not None:
            payload = NotificationResponse.model_validate(notification).model_dump_json()
            await self.cache.publish(channel_for(company_id, user_id), payload)
        return notification

    async def list_for_user(
        self, company_id: str, user_id: str, unread_only: bool = False, skip: int = 0, limit: int = 100
    ) -> Tuple[List[NotificationModel], int]:
        items = await self.repository.list_for_user(
            company_id, user_id, unread_only=unread_only, skip=skip, limit=limit
        )
        total = await self.repository.count_for_user(company_id, user_id, unread_only=unread_only)
        return items, total

    async def mark_read(self, notification_id: str, company_id: str, requester_id: str) -> NotificationModel:
        notification = await self.repository.get_by_id(notification_id, company_id)
        if notification is None:
            raise NotFoundException(message="Bildirim bulunamadı.")
        if notification.user_id != requester_id:
            raise AuthorizationException(message="Bu bildirime erişim izniniz yok.")
        return await self.repository.mark_read(notification)

    async def mark_all_read(self, company_id: str, user_id: str) -> int:
        return await self.repository.mark_all_read(company_id, user_id)
