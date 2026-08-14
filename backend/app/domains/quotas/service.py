"""Monthly usage quota enforcement.

Deliberately scoped to `"documents"` and `"drafts"` only, not
`"llm_tokens"` -- despite `kachow_llm_tokens_total` (see `app.observability.
ai_metrics`) existing as a *declared* Prometheus counter, that module's own
docstring is explicit that token counts "aren't exposed by
`BaseLLMClient.generate()` today" and the metric is "not wired up
everywhere yet." Enforcing a token quota here would mean inventing a number
to compare against a limit, which is worse than not having the feature --
a quota that sometimes silently undercounts would let a company blow past
what an admin thinks they configured. `"documents"` and `"drafts"` are
counted at their own real creation choke points instead (`DocumentService.
_register_document`, `DraftShareService`/`draft_recorder.record_draft`),
which is an honest, already-accurate count.
"""

from datetime import datetime, timezone
from typing import Optional

from app.api.exceptions.rate_limit import RateLimitException
from app.domains.quotas.repository import CompanyQuotaRepository, UsageCounterRepository

#: The only metrics this phase enforces quotas for -- see the module
#: docstring for why "llm_tokens" is not among them yet.
DOCUMENTS_METRIC = "documents"
DRAFTS_METRIC = "drafts"


def current_period(now: Optional[datetime] = None) -> str:
    """The current calendar-month bucket, `"YYYY-MM"`."""
    moment = now or datetime.now(timezone.utc)
    return moment.strftime("%Y-%m")


class QuotaService:
    def __init__(self, usage_repository: UsageCounterRepository, quota_repository: CompanyQuotaRepository):
        self.usage_repository = usage_repository
        self.quota_repository = quota_repository

    def _limit_for(self, quota, metric: str) -> Optional[int]:
        if quota is None:
            return None
        if metric == DOCUMENTS_METRIC:
            return quota.max_documents_per_month
        if metric == DRAFTS_METRIC:
            return quota.max_drafts_per_month
        return None

    async def check_and_increment(self, company_id: str, metric: str, amount: int = 1) -> None:
        """Raise if incrementing `metric` by `amount` would exceed
        `company_id`'s configured limit for the current month; otherwise
        record the usage.

        A company with no `company_quotas` row at all (the default -- rows
        are only created via `PATCH .../quota`) is unlimited: the check is
        opt-in per company, not a default cap every company silently
        inherits.

        Raises:
            RateLimitException: If the limit is set and would be exceeded.
                Reuses the existing 429 exception type rather than a new
                one -- a quota is conceptually the same "too much, too
                fast (or too much this period)" shape `app.api.rate_limit`
                already models.
        """
        quota = await self.quota_repository.get(company_id)
        limit = self._limit_for(quota, metric)
        period = current_period()
        if limit is not None:
            existing = await self.usage_repository.get(company_id, metric, period)
            current_count = existing.count if existing is not None else 0
            if current_count + amount > limit:
                raise RateLimitException(
                    message=(
                        f"Bu ay için {metric} kotası doldu "
                        f"({current_count}/{limit}). Kotayı artırmak için şirket yöneticinizle görüşün."
                    )
                )
        await self.usage_repository.increment(company_id, metric, period, amount)

    async def usage_summary(self, company_id: str) -> dict:
        """The current period's usage vs. limit for every enforced metric --
        for `GET /companies/{id}/analytics/summary`."""
        quota = await self.quota_repository.get(company_id)
        period = current_period()
        summary = {}
        for metric in (DOCUMENTS_METRIC, DRAFTS_METRIC):
            counter = await self.usage_repository.get(company_id, metric, period)
            summary[metric] = {
                "period": period,
                "used": counter.count if counter is not None else 0,
                "limit": self._limit_for(quota, metric),
            }
        return summary
