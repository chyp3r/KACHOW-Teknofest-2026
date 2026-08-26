from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class UsageCounterModel(Base, TimestampMixin):
    """Bir şirketin bir fatura döneminde tek bir metriğin işleyen sayacı.

    `period`, bir `DateTime` değil `"YYYY-MM"` string'idir -- kullanım her
    zaman keyfi bir pencere değil, her seferinde bütün bir takvim ayı
    üzerinden değerlendirilir (bkz. `app.domains.quotas.service.
    current_period`), bu yüzden karşılaştırılabilir/sıralanabilir bir
    string kova, her çağrı noktasında tarih artı kesme mantığından daha
    basittir. `(company_id, metric, period)` başına bir satır; `count`
    olay başına bir satır yerine yerinde artırılır, bu da bir kota
    kontrolünü potansiyel olarak binlerce satır üzerinde bir `COUNT(*)`
    yerine tek bir indeksli arama olarak tutar.

    `metric` bugün bilerek yalnızca `"documents"` ve `"drafts"`tir,
    `"llm_tokens"` değil -- token tabanlı bir kotanın `BaseLLMClient.
    generate()`'in henüz fiilen açığa çıkarmadığı bir sayıyı neden uydurmak
    zorunda kalacağı için `QuotaService`'in modül docstring'ine bakın.
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
