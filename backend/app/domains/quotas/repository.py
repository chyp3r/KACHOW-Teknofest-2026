from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.quotas.model.company_quota_model import CompanyQuotaModel
from app.domains.quotas.model.usage_counter_model import UsageCounterModel


class UsageCounterRepository:
    """`usage_counters` için repository (bkz. `UsageCounterModel`)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, company_id: str, metric: str, period: str) -> Optional[UsageCounterModel]:
        result = await self.db.execute(
            select(UsageCounterModel).where(
                UsageCounterModel.company_id == company_id,
                UsageCounterModel.metric == metric,
                UsageCounterModel.period == period,
            )
        )
        return result.scalar_one_or_none()

    async def increment(self, company_id: str, metric: str, period: str, amount: int = 1) -> UsageCounterModel:
        """`(company_id, metric, period)`'in sayacını getir ya da oluştur ve
        `amount` kadar ekle. Tek atomik bir `UPSERT ... ON CONFLICT DO
        UPDATE` değildir -- RLS kapsamlı `kachow_app` bağlantısı, bu kod
        tabanının geri kalanının dayandığı normal transaction/session
        yaşam döngüsü üzerinden zaten istek başına serileştirir (aynı
        mantık için `QuotaService`'in modül docstring'ine bakın;
        `AuditLogRepository.append`'in kendi oku-sonra-yaz `seq`
        hesaplaması için belgelediğiyle aynı), ve bir şirketten gelen bir
        aylık eşzamanlı yüklemeler, buradaki kaybolan bir güncellemenin
        pratikte önemli olacağı hacmin çok altındadır.
        """
        counter = await self.get(company_id, metric, period)
        if counter is None:
            counter = UsageCounterModel(
                id=uuid4().hex, company_id=company_id, metric=metric, period=period, count=0
            )
            self.db.add(counter)
        counter.count += amount
        await self.db.flush()
        return counter


class CompanyQuotaRepository:
    """`company_quotas` için repository (bkz. `CompanyQuotaModel`)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, company_id: str) -> Optional[CompanyQuotaModel]:
        result = await self.db.execute(
            select(CompanyQuotaModel).where(CompanyQuotaModel.company_id == company_id)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        company_id: str,
        max_documents_per_month: Optional[int],
        max_drafts_per_month: Optional[int],
    ) -> CompanyQuotaModel:
        quota = await self.get(company_id)
        if quota is None:
            quota = CompanyQuotaModel(id=uuid4().hex, company_id=company_id)
            self.db.add(quota)
        quota.max_documents_per_month = max_documents_per_month
        quota.max_drafts_per_month = max_drafts_per_month
        await self.db.flush()
        return quota
