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
from typing import Any, Dict, List, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.chat.model.chat_model import ChatSessionModel
from app.domains.companies.model.company_model import CompanyModel
from app.domains.documents.model.document_model import DocumentModel
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.users.model.user_model import UserModel
from app.observability.model.guardrail_model import GuardrailEventModel
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

    async def new_user_count(self, days: int = 7) -> int:
        """Son ``days`` günde oluşturulan kullanıcı sayısı."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.db.execute(
            select(func.count(UserModel.id)).where(UserModel.created_at >= since)
        )
        return result.scalar_one()

    async def daily_activity(self, days: int = 30) -> List[Dict[str, Any]]:
        """Gün başına ``{date, active_users, runs}`` -- son ``days`` gün.

        ``runs.created_at`` gününe göre gruplanır; ``active_users`` o gün
        en az bir ``runs`` satırı olan ayrık ``user_id`` sayısıdır. Hiç
        çalışması olmayan günler listede yer almaz (çağıran tarafında
        doldurulur).
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)
        day = func.date_trunc("day", RunModel.created_at)
        result = await self.db.execute(
            select(
                day.label("day"),
                func.count(func.distinct(RunModel.user_id)).label("active_users"),
                func.count(RunModel.id).label("runs"),
            )
            .where(RunModel.created_at >= since)
            .group_by(day)
            .order_by(day)
        )
        return [
            {
                "date": row.day.date().isoformat() if row.day is not None else None,
                "active_users": int(row.active_users or 0),
                "runs": int(row.runs or 0),
            }
            for row in result.all()
        ]

    async def runs_by_intent(self) -> List[Tuple[str, int]]:
        result = await self.db.execute(
            select(RunModel.intent, func.count(RunModel.id)).group_by(RunModel.intent)
        )
        return list(result.all())

    async def guardrail_by_decision(self) -> List[Tuple[str, int]]:
        result = await self.db.execute(
            select(GuardrailEventModel.decision, func.count(GuardrailEventModel.id)).group_by(
                GuardrailEventModel.decision
            )
        )
        return list(result.all())

    async def top_users(self, limit: int = 15) -> List[Dict[str, Any]]:
        """En çok iş akışı çalıştıran kullanıcılar; kullanıcı başına
        çalışma/taslak/evrak/sohbet sayısı ve son etkinlik.

        ``company_rollup`` ile aynı fan-out tuzağından kaçınmak için tek
        join yerine ayrı gruplanmış sayımlar Python'da birleştirilir.
        """
        users_result = await self.db.execute(
            select(
                UserModel.id,
                UserModel.username,
                UserModel.role,
                UserModel.company_id,
                CompanyModel.name,
            ).join(CompanyModel, CompanyModel.id == UserModel.company_id, isouter=True)
        )
        users = users_result.all()

        run_counts = dict(
            (
                await self.db.execute(
                    select(RunModel.user_id, func.count(RunModel.id))
                    .where(RunModel.user_id.is_not(None))
                    .group_by(RunModel.user_id)
                )
            ).all()
        )
        last_seen = dict(
            (
                await self.db.execute(
                    select(RunModel.user_id, func.max(RunModel.created_at))
                    .where(RunModel.user_id.is_not(None))
                    .group_by(RunModel.user_id)
                )
            ).all()
        )
        draft_counts = dict(
            (
                await self.db.execute(
                    select(DraftModel.user_id, func.count(DraftModel.id))
                    .where(DraftModel.user_id.is_not(None), DraftModel.is_deleted.is_(False))
                    .group_by(DraftModel.user_id)
                )
            ).all()
        )
        document_counts = dict(
            (
                await self.db.execute(
                    select(DocumentModel.owner_id, func.count(DocumentModel.id)).group_by(
                        DocumentModel.owner_id
                    )
                )
            ).all()
        )
        session_counts = dict(
            (
                await self.db.execute(
                    select(ChatSessionModel.user_id, func.count(ChatSessionModel.id))
                    .where(ChatSessionModel.user_id.is_not(None))
                    .group_by(ChatSessionModel.user_id)
                )
            ).all()
        )

        rows = [
            {
                "user_id": user_id,
                "username": username,
                "role": role,
                "company_id": company_id,
                "company_name": company_name,
                "run_count": int(run_counts.get(user_id, 0)),
                "draft_count": int(draft_counts.get(user_id, 0)),
                "document_count": int(document_counts.get(user_id, 0)),
                "session_count": int(session_counts.get(user_id, 0)),
                "last_seen": (
                    last_seen[user_id].isoformat()
                    if last_seen.get(user_id) is not None
                    else None
                ),
            }
            for user_id, username, role, company_id, company_name in users
        ]
        rows.sort(key=lambda row: (row["run_count"], row["session_count"]), reverse=True)
        return rows[:limit]

    async def last_activity_by_company(self) -> dict:
        """`{company_id: last_run_created_at}` -- şirket başına en son `runs`
        satırı; `GET /root/health`'in şirket başına bayatlık (staleness)
        görünümü için kullanılır."""
        result = await self.db.execute(
            select(RunModel.company_id, func.max(RunModel.created_at)).group_by(RunModel.company_id)
        )
        return dict(result.all())
