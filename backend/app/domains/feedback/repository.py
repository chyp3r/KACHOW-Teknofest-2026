from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.feedback.model.feedback_model import FeedbackModel


class FeedbackRepository:
    """`feedback` için repository (bkz. `FeedbackModel`).

    Her metot açık bir `company_id` alır; bu, tenancy çalışmasından beri
    tüm diğer repository'lerle aynı kural -- RLS bunu destekler, yerini
    almaz.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, feedback_id: str, company_id: str) -> Optional[FeedbackModel]:
        result = await self.db.execute(
            select(FeedbackModel).where(
                FeedbackModel.id == feedback_id,
                FeedbackModel.company_id == company_id,
                FeedbackModel.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def find_existing_vote(
        self, company_id: str, user_id: str, target_kind: str, content_hash: str
    ) -> Optional[FeedbackModel]:
        """Bu tam metin üzerinde yeni bir oyun çakışacağı satır, varsa --
        `FeedbackService.submit` yeni bir kayıt eklemek yerine bunun
        üzerine upsert yapar. Soft-delete edilmiş satırlar döndürülmez:
        bir oyunu geri çeken ve aynı metin üzerinde tekrar oy veren
        kullanıcı, sessizce silinmiş kaydı diriltmek yerine yeni bir
        satır almalıdır."""
        result = await self.db.execute(
            select(FeedbackModel).where(
                FeedbackModel.company_id == company_id,
                FeedbackModel.user_id == user_id,
                FeedbackModel.target_kind == target_kind,
                FeedbackModel.content_hash == content_hash,
                FeedbackModel.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def create(self, feedback: FeedbackModel) -> FeedbackModel:
        self.db.add(feedback)
        await self.db.flush()
        return feedback

    async def update_vote(
        self,
        feedback: FeedbackModel,
        *,
        signal: str,
        comment: Optional[str],
        dimensions: Optional[dict],
        context: Optional[dict],
    ) -> FeedbackModel:
        """Mevcut bir oyu yerinde üzerine yazar -- aynı metne tekrar oy
        vermek, çoğaltmak yerine günceller (bkz. `FeedbackModel`'ın
        docstring'i)."""
        feedback.signal = signal
        feedback.comment = comment
        feedback.dimensions = dimensions
        feedback.context = context
        feedback.is_deleted = False
        await self.db.flush()
        return feedback

    async def list_filtered(
        self,
        company_id: str,
        user_id: Optional[str] = None,
        target_kind: Optional[str] = None,
        signal: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[FeedbackModel]:
        query = select(FeedbackModel).where(
            FeedbackModel.company_id == company_id, FeedbackModel.is_deleted.is_(False)
        )
        if user_id is not None:
            query = query.where(FeedbackModel.user_id == user_id)
        if target_kind is not None:
            query = query.where(FeedbackModel.target_kind == target_kind)
        if signal is not None:
            query = query.where(FeedbackModel.signal == signal)
        query = query.order_by(FeedbackModel.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_filtered(
        self,
        company_id: str,
        user_id: Optional[str] = None,
        target_kind: Optional[str] = None,
        signal: Optional[str] = None,
    ) -> int:
        query = select(func.count(FeedbackModel.id)).where(
            FeedbackModel.company_id == company_id, FeedbackModel.is_deleted.is_(False)
        )
        if user_id is not None:
            query = query.where(FeedbackModel.user_id == user_id)
        if target_kind is not None:
            query = query.where(FeedbackModel.target_kind == target_kind)
        if signal is not None:
            query = query.where(FeedbackModel.signal == signal)
        result = await self.db.execute(query)
        return result.scalar_one()

    async def soft_delete(self, feedback: FeedbackModel) -> None:
        feedback.is_deleted = True
        await self.db.flush()

    async def count_by_signal(self, company_id: str) -> dict:
        """`{"like": N, "dislike": M}` -- `GET /companies/{id}/feedback/stats`
        uç noktasının başında yer alan özet kartı."""
        query = (
            select(FeedbackModel.signal, func.count(FeedbackModel.id))
            .where(FeedbackModel.company_id == company_id, FeedbackModel.is_deleted.is_(False))
            .group_by(FeedbackModel.signal)
        )
        result = await self.db.execute(query)
        return {signal: count for signal, count in result.all()}

    async def count_by_target_kind(self, company_id: str) -> dict:
        query = (
            select(FeedbackModel.target_kind, func.count(FeedbackModel.id))
            .where(FeedbackModel.company_id == company_id, FeedbackModel.is_deleted.is_(False))
            .group_by(FeedbackModel.target_kind)
        )
        result = await self.db.execute(query)
        return {kind: count for kind, count in result.all()}
