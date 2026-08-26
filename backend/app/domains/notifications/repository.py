from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.notifications.model.notification_model import NotificationModel


class NotificationRepository:
    """`notifications` için repository (bkz. `NotificationModel`).

    Her metot açık bir `company_id` alır, tenancy çalışmasından bu yana
    diğer tüm repository'lerle aynı kural.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, notification_id: str, company_id: str) -> Optional[NotificationModel]:
        result = await self.db.execute(
            select(NotificationModel).where(
                NotificationModel.id == notification_id, NotificationModel.company_id == company_id
            )
        )
        return result.scalar_one_or_none()

    async def create(self, notification: NotificationModel) -> NotificationModel:
        self.db.add(notification)
        await self.db.flush()
        return notification

    async def list_for_user(
        self,
        company_id: str,
        user_id: str,
        unread_only: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> List[NotificationModel]:
        query = select(NotificationModel).where(
            NotificationModel.company_id == company_id, NotificationModel.user_id == user_id
        )
        if unread_only:
            query = query.where(NotificationModel.read_at.is_(None))
        query = query.order_by(NotificationModel.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_for_user(self, company_id: str, user_id: str, unread_only: bool = False) -> int:
        query = select(func.count(NotificationModel.id)).where(
            NotificationModel.company_id == company_id, NotificationModel.user_id == user_id
        )
        if unread_only:
            query = query.where(NotificationModel.read_at.is_(None))
        result = await self.db.execute(query)
        return result.scalar_one()

    async def mark_read(self, notification: NotificationModel) -> NotificationModel:
        if notification.read_at is None:
            notification.read_at = datetime.now(timezone.utc)
            await self.db.flush()
        return notification

    async def mark_all_read(self, company_id: str, user_id: str) -> int:
        result = await self.db.execute(
            update(NotificationModel)
            .where(
                NotificationModel.company_id == company_id,
                NotificationModel.user_id == user_id,
                NotificationModel.read_at.is_(None),
            )
            .values(read_at=datetime.now(timezone.utc))
        )
        await self.db.flush()
        return result.rowcount
