"""Halihazırda var olan tablolar üzerinde düz SQLAlchemy toplama (aggregate)
sorguları -- yeni bir pipeline, materialized view ya da rollup tablosu yok
(bkz. kiracılık planının kendi §6.1'i: "demo ölçeğinde gerekçesi yok,
kiracılığın zorlanacağı üçüncü bir yer olurdu"). Bunları Redis arkasında
önbelleğe alan `AnalyticsService`'tir; bu modül sadece sorgu çalıştırır.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.model.document_model import DocumentModel
from app.domains.drafts.model.draft_model import DraftModel
from app.observability.model.guardrail_model import GuardrailEventModel
from app.observability.model.run_model import RunModel


class AnalyticsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def document_count(self, company_id: str) -> int:
        result = await self.db.execute(
            select(func.count(DocumentModel.id)).where(DocumentModel.company_id == company_id)
        )
        return result.scalar_one()

    async def draft_stats(self, company_id: str) -> dict:
        """Her taslak *versiyonu* (`DraftRepository.list_drafts`'ın gösterdiği
        oturuma göre daraltılmış liste değil) -- bir hacim/kalite analitik
        özeti için her revizyon gerçek bir iş birimidir, gizlenecek bir şey
        değil."""
        result = await self.db.execute(
            select(
                func.count(DraftModel.id),
                func.avg(DraftModel.confidence_score),
                func.sum(cast(DraftModel.requires_human_approval, Integer)),
            ).where(DraftModel.company_id == company_id, DraftModel.is_deleted.is_(False))
        )
        total, avg_confidence, requires_approval = result.one()
        return {
            "total": total or 0,
            "avg_confidence_score": float(avg_confidence) if avg_confidence is not None else None,
            "requires_human_approval": int(requires_approval or 0),
        }

    async def run_status_breakdown(self, company_id: str) -> List[Tuple[str, int]]:
        result = await self.db.execute(
            select(RunModel.status, func.count(RunModel.id))
            .where(RunModel.company_id == company_id)
            .group_by(RunModel.status)
        )
        return list(result.all())

    async def guardrail_breakdown(
        self,
        company_id: str,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> List[Tuple[str, str, str, int]]:
        """`(stage, kind, decision, count)`, isteğe bağlı olarak tarih aralığıyla sınırlandırılmış."""
        query = select(
            GuardrailEventModel.stage,
            GuardrailEventModel.kind,
            GuardrailEventModel.decision,
            func.count(GuardrailEventModel.id),
        ).where(GuardrailEventModel.company_id == company_id)
        if date_from is not None:
            query = query.where(GuardrailEventModel.created_at >= date_from)
        if date_to is not None:
            query = query.where(GuardrailEventModel.created_at <= date_to)
        query = query.group_by(
            GuardrailEventModel.stage, GuardrailEventModel.kind, GuardrailEventModel.decision
        )
        result = await self.db.execute(query)
        return list(result.all())

    async def unit_volume(self, company_id: str) -> List[Tuple[Optional[str], int]]:
        """`destination`'a göre gruplanmış taslak sayısı -- yapay zekânın
        yönlendirme kararı, serbest metin bir birim adı (bkz.
        `DraftModel.destination`'ın kendi docstring'i). Burada `units` ile
        join yapılmıyor; router endpoint'i adları çağıranın kendi
        `GET /units` listesiyle eşleştiriyor, tıpkı `GET
        /units/{id}/suggested-recipients`'in kendi birim-adı çözümlemesi
        için zaten belgelediği gibi."""
        result = await self.db.execute(
            select(DraftModel.destination, func.count(DraftModel.id))
            .where(DraftModel.company_id == company_id, DraftModel.is_deleted.is_(False))
            .group_by(DraftModel.destination)
            .order_by(func.count(DraftModel.id).desc())
        )
        return list(result.all())

    async def active_user_count(self, company_id: str, days: int = 7) -> int:
        """Son `days` gün içinde en az bir `runs` satırı (bir sohbet turu)
        olan tekil (distinct) kullanıcılar -- bugün elde mevcut dürüst vekil
        (proxy) metrik, çünkü bu kod tabanında hiçbir yerde giriş
        zaman damgası tutulmuyor (var olmayan `users.last_login_at` yerine
        bunun neden kullanıldığına dair `AnalyticsService.summary`'nin
        kendi docstring'ine bakın)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.db.execute(
            select(func.count(func.distinct(RunModel.user_id))).where(
                RunModel.company_id == company_id,
                RunModel.user_id.is_not(None),
                RunModel.created_at >= since,
            )
        )
        return result.scalar_one()

    async def timeseries(
        self,
        company_id: str,
        metric: str,
        date_from: datetime,
        date_to: datetime,
        bucket: str = "day",
    ) -> List[Tuple[datetime, int]]:
        """Bir metrik için `[(bucket_start, count), ...]`, `date_trunc` ile kovalanmış (bucketed).

        `bucket` `"day"` veya `"week"` -- doğrudan Postgres'in `date_trunc`'ına
        veriliyor, o da yalnızca küçük sabit bir kelime dağarcığını kabul
        ediyor; router bunu buraya ulaşmadan önce tam olarak o küme
        karşısında doğruluyor (asla daha geniş açık bir değerden
        enterpole edilmiyor).
        """
        model, date_column, extra_filter = {
            "documents": (DocumentModel, DocumentModel.created_at, None),
            "drafts": (DraftModel, DraftModel.created_at, DraftModel.is_deleted.is_(False)),
            "runs": (RunModel, RunModel.created_at, None),
            "guardrail_blocks": (
                GuardrailEventModel,
                GuardrailEventModel.created_at,
                GuardrailEventModel.decision == "blocked",
            ),
        }[metric]

        bucket_expr = func.date_trunc(bucket, date_column)
        query = (
            select(bucket_expr.label("bucket"), func.count())
            .select_from(model)
            .where(
                model.company_id == company_id,
                date_column >= date_from,
                date_column <= date_to,
            )
        )
        if extra_filter is not None:
            query = query.where(extra_filter)
        query = query.group_by(bucket_expr).order_by(bucket_expr)
        result = await self.db.execute(query)
        return list(result.all())
