"""Plain SQLAlchemy aggregate queries over already-existing tables -- no new
pipeline, no materialized view or rollup table (see the tenancy plan's own
§6.1: "demo ölçeğinde gerekçesi yok, kiracılığın zorlanacağı üçüncü bir yer
olurdu"). `AnalyticsService` is what caches these behind Redis; this module
only ever runs a query.
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
        """Every draft *version* (not the session-collapsed listing
        `DraftRepository.list_drafts` shows) -- for a volume/quality
        analytics summary, each revision is a real unit of work, not
        something to hide."""
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
        """`(stage, kind, decision, count)`, optionally windowed."""
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
        """Draft count grouped by `destination` -- the AI's routing
        decision, a free-text unit name (see `DraftModel.destination`'s own
        docstring). Not joined against `units` here; the router endpoint
        matches names against the caller's own `GET /units` listing, same
        as `GET /units/{id}/suggested-recipients` already documents doing
        for its own unit-name resolution."""
        result = await self.db.execute(
            select(DraftModel.destination, func.count(DraftModel.id))
            .where(DraftModel.company_id == company_id, DraftModel.is_deleted.is_(False))
            .group_by(DraftModel.destination)
            .order_by(func.count(DraftModel.id).desc())
        )
        return list(result.all())

    async def active_user_count(self, company_id: str, days: int = 7) -> int:
        """Distinct users with at least one `runs` row (a chat turn) in the
        last `days` days -- the honest proxy available today, since no
        login-timestamp is tracked anywhere in this codebase (see
        `AnalyticsService.summary`'s own docstring for why this isn't
        `users.last_login_at`, which does not exist)."""
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
        """`[(bucket_start, count), ...]` for one metric, `date_trunc`-bucketed.

        `bucket` is `"day"` or `"week"` -- passed straight to Postgres'
        `date_trunc`, which only accepts a small fixed vocabulary; the
        router validates it against exactly that set before it ever reaches
        here (never interpolated from a wider-open value).
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
