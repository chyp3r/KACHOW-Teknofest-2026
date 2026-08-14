"""System-wide (unscoped) aggregate queries backing `GET /root/*` -- the
root console. Every method here deliberately has no `company_id` filter,
unlike every other repository in this codebase; that is the entire point
of this module existing separately from `app.domains.analytics.
repository.AnalyticsRepository` rather than just calling that with
`company_id=None` (which its queries don't support, and shouldn't -- a
per-company repository silently accepting "no company" would be an easy
way to leak cross-tenant data through a forgotten filter).

Runs on the same RLS-scoped `kachow_app` connection as everything else --
these queries are reachable through `GET /root/*` (root-only), and root's
own session carries `app.is_root='on'`, which every `tenant_isolation`
policy already ORs in (see migration `0013_rls`), so no separate DB
connection or bypass is needed here.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.companies.model.company_model import CompanyModel
from app.domains.documents.model.document_model import DocumentModel
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.users.model.user_model import UserModel
from app.observability.model.run_model import RunModel


class RootRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def total_companies(self) -> int:
        result = await self.db.execute(select(func.count(CompanyModel.id)))
        return result.scalar_one()

    async def total_users(self) -> int:
        result = await self.db.execute(select(func.count(UserModel.id)))
        return result.scalar_one()

    async def total_documents(self) -> int:
        result = await self.db.execute(select(func.count(DocumentModel.id)))
        return result.scalar_one()

    async def total_drafts(self) -> int:
        result = await self.db.execute(
            select(func.count(DraftModel.id)).where(DraftModel.is_deleted.is_(False))
        )
        return result.scalar_one()

    async def run_status_totals(self) -> List[Tuple[str, int]]:
        result = await self.db.execute(select(RunModel.status, func.count(RunModel.id)).group_by(RunModel.status))
        return list(result.all())

    async def users_by_role(self) -> List[Tuple[str, int]]:
        result = await self.db.execute(select(UserModel.role, func.count(UserModel.id)).group_by(UserModel.role))
        return list(result.all())

    async def active_user_count(self, days: int = 7) -> int:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.db.execute(
            select(func.count(func.distinct(RunModel.user_id))).where(
                RunModel.user_id.is_not(None), RunModel.created_at >= since
            )
        )
        return result.scalar_one()

    async def company_rollup(self) -> List[dict]:
        """One row per company: identity plus user/document/draft counts.

        Three grouped counts, not one join -- `documents`/`drafts` both
        joining against `companies` in a single query would multiply rows
        (a company with 5 documents and 3 drafts would otherwise produce 15
        joined rows before aggregation), the classic fan-out trap; three
        separate `GROUP BY company_id` queries merged in Python avoids it
        without needing `COUNT(DISTINCT ...)` gymnastics.
        """
        companies_result = await self.db.execute(
            select(CompanyModel.id, CompanyModel.name, CompanyModel.slug, CompanyModel.is_active)
        )
        companies = companies_result.all()

        user_counts = dict(
            (await self.db.execute(select(UserModel.company_id, func.count(UserModel.id)).group_by(UserModel.company_id))).all()
        )
        document_counts = dict(
            (
                await self.db.execute(
                    select(DocumentModel.company_id, func.count(DocumentModel.id)).group_by(
                        DocumentModel.company_id
                    )
                )
            ).all()
        )
        draft_counts = dict(
            (
                await self.db.execute(
                    select(DraftModel.company_id, func.count(DraftModel.id))
                    .where(DraftModel.is_deleted.is_(False))
                    .group_by(DraftModel.company_id)
                )
            ).all()
        )

        return [
            {
                "company_id": company_id,
                "name": name,
                "slug": slug,
                "is_active": is_active,
                "user_count": user_counts.get(company_id, 0),
                "document_count": document_counts.get(company_id, 0),
                "draft_count": draft_counts.get(company_id, 0),
            }
            for company_id, name, slug, is_active in companies
        ]

    async def last_activity_by_company(self) -> dict:
        """`{company_id: last_run_created_at}` -- the most recent `runs` row
        per company, for `GET /root/health`'s per-company staleness view."""
        result = await self.db.execute(
            select(RunModel.company_id, func.max(RunModel.created_at)).group_by(RunModel.company_id)
        )
        return dict(result.all())
