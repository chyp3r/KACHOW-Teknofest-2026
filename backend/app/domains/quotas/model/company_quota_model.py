from typing import Optional

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class CompanyQuotaModel(Base, TimestampMixin):
    """Bir şirketin aylık kaynak tavanları. Şirket başına bir satır; her
    şirket için önceden tohumlanmak yerine ilk kota kontrolünde tembelce
    oluşturulur (bkz. `QuotaService.get_or_default`) -- yokluk "sınırsız"
    anlamına gelir, aşağıdaki `NULL` limitlerin taşıdığı aynı kural.

    Herhangi bir limitte `NULL`, o kaynak için sınırsız anlamına gelir --
    hiç satırı olmayan bir şirket (bu opt-in olduğundan yaygın durum) her
    ikisinde de basitçe sınırsızdır.
    """

    __tablename__ = "company_quotas"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, unique=True, index=True
    )
    max_documents_per_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_drafts_per_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: Faz C3 (#187) -- `POST /companies/{id}/training-runs`'ı sınırlar,
    #: diğer iki limitle aynı `usage_counters` mekanizması üzerinden sayılır.
    max_training_runs_per_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
