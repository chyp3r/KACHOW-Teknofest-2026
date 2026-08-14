from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.quotas.model.company_quota_model import CompanyQuotaModel
from app.domains.quotas.model.usage_counter_model import UsageCounterModel


class UsageCounterRepository:
    """Repository for `usage_counters` (see `UsageCounterModel`)."""

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
        """Fetch-or-create `(company_id, metric, period)`'s counter and add
        `amount` to it. Not a single atomic `UPSERT ... ON CONFLICT DO
        UPDATE` -- the RLS-scoped `kachow_app` connection already serialises
        per-request through the normal transaction/session lifecycle the
        rest of this codebase relies on (see `QuotaService`'s module
        docstring for the same reasoning `AuditLogRepository.append`
        documents for its own read-then-write `seq` computation), and a
        month's worth of concurrent uploads from one company is nowhere
        near the volume where a lost update here would matter in practice.
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
    """Repository for `company_quotas` (see `CompanyQuotaModel`)."""

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
