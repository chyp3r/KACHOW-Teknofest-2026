"""`AnalyticsService` -- thin caching + shaping layer over `AnalyticsRepository`'s
raw aggregate queries, per the tenancy plan's §6.1: a 60s Redis cache keyed
by `(company_id, metric, range)` is the entire caching story here, no
materialized view or rollup table.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from app.domains.analytics.repository import AnalyticsRepository
from app.domains.quotas.service import QuotaService
from app.infrastructure.cache.redis import RedisCache
from app.observability import company_metrics

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60
_VALID_BUCKETS = ("day", "week")
_VALID_TIMESERIES_METRICS = ("documents", "drafts", "runs", "guardrail_blocks")


class AnalyticsService:
    def __init__(
        self,
        repository: AnalyticsRepository,
        cache: RedisCache,
        quota_service: Optional[QuotaService] = None,
    ):
        self.repository = repository
        self.cache = cache
        self.quota_service = quota_service

    async def _cached(self, key: str, compute):
        raw = await self.cache.get(key)
        if raw is not None:
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                pass
        value = await compute()
        await self.cache.set(key, json.dumps(value, default=str), expire_seconds=_CACHE_TTL_SECONDS)
        return value

    async def summary(self, company_id: str) -> dict:
        """The company overview `GET /companies/{id}/analytics/summary` returns.

        Also opportunistically refreshes `kachow_company_active_users` (see
        `app.observability.company_metrics`'s own docstring on why this is
        the one point that gauge gets updated, not a continuous timer) --
        a side effect of computing the number this endpoint needed anyway,
        not an extra query paid just for the metric.
        """

        async def compute():
            document_count = await self.repository.document_count(company_id)
            draft_stats = await self.repository.draft_stats(company_id)
            run_status = dict(await self.repository.run_status_breakdown(company_id))
            active_users = await self.repository.active_user_count(company_id, days=7)
            guardrail_rows = await self.repository.guardrail_breakdown(company_id)
            guardrail_blocked_total = sum(
                count for _stage, _kind, decision, count in guardrail_rows if decision == "blocked"
            )
            usage = {}
            if self.quota_service is not None:
                raw_usage = await self.quota_service.usage_summary(company_id)
                usage = {metric: values for metric, values in raw_usage.items()}
            return {
                "company_id": company_id,
                "document_count": document_count,
                "draft_stats": draft_stats,
                "run_status": run_status,
                "active_users_7d": active_users,
                "guardrail_blocked_total": guardrail_blocked_total,
                "usage": usage,
            }

        result = await self._cached(f"analytics:summary:{company_id}", compute)

        slug = company_metrics.cached_slug(company_id)
        if slug is not None:
            company_metrics.set_active_users(slug, result["active_users_7d"])

        return result

    async def timeseries(
        self,
        company_id: str,
        metric: str,
        date_from: Optional[datetime],
        date_to: Optional[datetime],
        bucket: str,
    ) -> List[dict]:
        if metric not in _VALID_TIMESERIES_METRICS:
            raise ValueError(f"Bilinmeyen metrik: {metric}")
        if bucket not in _VALID_BUCKETS:
            raise ValueError(f"Bilinmeyen bucket: {bucket}")
        resolved_to = date_to or datetime.now(timezone.utc)
        resolved_from = date_from or (resolved_to - timedelta(days=30))

        cache_key = (
            f"analytics:timeseries:{company_id}:{metric}:{bucket}:"
            f"{resolved_from.isoformat()}:{resolved_to.isoformat()}"
        )

        async def compute():
            rows = await self.repository.timeseries(
                company_id, metric, resolved_from, resolved_to, bucket
            )
            return [{"bucket": bucket_start.isoformat(), "count": count} for bucket_start, count in rows]

        return await self._cached(cache_key, compute)

    async def units(self, company_id: str) -> List[dict]:
        async def compute():
            rows = await self.repository.unit_volume(company_id)
            return [{"destination": destination, "count": count} for destination, count in rows]

        return await self._cached(f"analytics:units:{company_id}", compute)

    async def guardrails(self, company_id: str) -> List[dict]:
        async def compute():
            rows = await self.repository.guardrail_breakdown(company_id)
            return [
                {"stage": stage, "kind": kind, "decision": decision, "count": count}
                for stage, kind, decision, count in rows
            ]

        return await self._cached(f"analytics:guardrails:{company_id}", compute)
