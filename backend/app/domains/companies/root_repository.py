"""`GET /root/*` -- root konsolu -- için sistem geneli (kapsamsız) toplu
sorgular. Buradaki her metot bilinçli olarak `company_id` filtresi
taşımaz; bu, kod tabanındaki diğer tüm repository'lerin aksine bir
durumdur. Bu modülün `app.domains.analytics.repository.
AnalyticsRepository`'yi `company_id=None` ile çağırmak yerine ayrı bir
modül olarak var olmasının tüm nedeni de budur (o repository'nin
sorguları bunu desteklemiyor ve desteklememeli de -- şirkete özel bir
repository'nin "şirket yok" durumunu sessizce kabul etmesi, unutulan bir
filtre yüzünden kiracılar arası veri sızdırmanın kolay bir yolu olurdu).

Diğer her şeyle aynı RLS kapsamlı `kachow_app` bağlantısı üzerinde
çalışır -- bu sorgulara `GET /root/*` (yalnızca root) üzerinden
erişilir ve root'un kendi oturumu, her `tenant_isolation` politikasının
zaten OR ile eklediği `app.is_root='on'` bayrağını taşır (bkz. `0013_rls`
migration'ı); bu yüzden burada ayrı bir DB bağlantısına veya bypass'a
gerek yoktur.
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
        """Şirket başına bir satır: kimlik bilgisi artı kullanıcı/belge/taslak sayıları.

        Tek bir join yerine üç ayrı gruplanmış sayım -- `documents`/`drafts`
        tablolarının ikisinin de `companies` ile tek bir sorguda join
        edilmesi satırları çoğaltırdı (5 belgesi ve 3 taslağı olan bir
        şirket, agregasyondan önce 15 join'li satır üretirdi), klasik
        fan-out tuzağı; Python'da birleştirilen üç ayrı
        `GROUP BY company_id` sorgusu, `COUNT(DISTINCT ...)` cambazlığına
        gerek kalmadan bunu önler.
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
        """`{company_id: last_run_created_at}` -- şirket başına en son `runs`
        satırı; `GET /root/health`'in şirket başına bayatlık (staleness)
        görünümü için kullanılır."""
        result = await self.db.execute(
            select(RunModel.company_id, func.max(RunModel.created_at)).group_by(RunModel.company_id)
        )
        return dict(result.all())
