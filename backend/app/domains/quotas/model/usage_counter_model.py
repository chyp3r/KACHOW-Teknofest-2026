from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class UsageCounterModel(Base, TimestampMixin):
    """One company's running count of one metric within one billing period.

    `period` is a `"YYYY-MM"` string, not a `DateTime` -- usage is always
    reasoned about a whole calendar month at a time (see
    `app.domains.quotas.service.current_period`), never an arbitrary window,
    so a comparable/sortable string bucket is simpler than a date plus
    truncation logic at every call site. One row per `(company_id, metric,
    period)`; `count` is incremented in place rather than one row per event,
    which is what keeps a quota check a single indexed lookup instead of a
    `COUNT(*)` over potentially thousands of rows.

    `metric` is deliberately only `"documents"` and `"drafts"` today, not
    `"llm_tokens"` -- see `QuotaService`'s module docstring for why a token-
    based quota would have to fabricate a number `BaseLLMClient.generate()`
    does not actually expose yet.
    """

    __tablename__ = "usage_counters"
    __table_args__ = (
        UniqueConstraint("company_id", "metric", "period", name="uq_usage_counters_company_metric_period"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    metric: Mapped[str] = mapped_column(String, nullable=False)
    period: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
