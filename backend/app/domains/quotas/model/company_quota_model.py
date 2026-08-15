from typing import Optional

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class CompanyQuotaModel(Base, TimestampMixin):
    """A company's monthly resource ceilings. One row per company, created
    lazily on first quota check (see `QuotaService.get_or_default`) rather
    than seeded for every company up front -- absence means "unlimited," the
    same convention `NULL` limits below carry.

    `NULL` on either limit means unlimited for that resource -- a company
    with no row at all (the common case, since this is opt-in) is simply
    unlimited on both.
    """

    __tablename__ = "company_quotas"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, unique=True, index=True
    )
    max_documents_per_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_drafts_per_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: Faz C3 (#187) -- caps `POST /companies/{id}/training-runs`, counted
    #: via the same `usage_counters` mechanism as the other two limits.
    max_training_runs_per_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
