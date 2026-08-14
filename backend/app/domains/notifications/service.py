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
    """The Redis pub/sub channel one user's live notification stream listens on.

    Shared between `NotificationService.create` (publisher) and
    `app.domains.notifications.router`'s SSE endpoint (subscriber) --
    `company_id` is folded into the channel name even though `user_id`
    alone is already globally unique, purely so a stray cross-company
    channel collision is structurally impossible, not just unlikely.
    """
    return f"notifications:{company_id}:{user_id}"


class NotificationService:
    """Service for `notifications` -- read/write plus the live-push side effect.

    Deliberately no `bypasses_ownership` company-wide view (see
    `NotificationModel`'s docstring): every method here is scoped to the
    caller's own `user_id`, full stop.
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
        """Write a notification row, then best-effort publish it live.

        Args:
            company_id: Tenant scope.
            user_id: Who this notification is for.
            type: A short machine tag (see `NotificationModel.type`).
            title: Human-readable headline.
            body: Optional human-readable detail.
            resource_type: What the notification is about (e.g. "draft_share").
            resource_id: The related row's id.

        Returns:
            The persisted `NotificationModel`. The DB write always happens;
            the Redis publish below is a pure side effect on top of it, so a
            Redis outage never prevents the notification from existing --
            see `RedisCache.publish`'s own docstring for why this ordering
            (write first, then best-effort push) is deliberate.
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
