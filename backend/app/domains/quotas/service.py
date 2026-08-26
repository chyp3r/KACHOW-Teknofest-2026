"""Aylık kullanım kotası uygulaması.

Bilerek yalnızca `"documents"` ve `"drafts"` ile sınırlandırılmıştır,
`"llm_tokens"` ile değil -- `kachow_llm_tokens_total` (bkz.
`app.observability.ai_metrics`) *bildirilmiş* bir Prometheus sayacı olarak
var olmasına rağmen, o modülün kendi docstring'i token sayılarının "bugün
`BaseLLMClient.generate()` tarafından açığa çıkarılmadığını" ve metriğin
"henüz her yerde bağlanmadığını" açıkça belirtir. Burada bir token kotası
uygulamak, bir limitle karşılaştırmak için bir sayı uydurmak anlamına
gelirdi, ki bu özelliğin hiç olmamasından daha kötüdür -- bazen sessizce
eksik sayan bir kota, bir şirketin bir yöneticinin yapılandırdığını
düşündüğü şeyi aşmasına izin verirdi. `"documents"` ve `"drafts"` bunun
yerine kendi gerçek oluşturma darboğaz noktalarında sayılır
(`DocumentService._register_document`, `DraftShareService`/
`draft_recorder.record_draft`), ki bu dürüst, zaten doğru bir sayımdır.
"""

from datetime import datetime, timezone
from typing import Optional

from app.api.exceptions.rate_limit import RateLimitException
from app.domains.quotas.repository import CompanyQuotaRepository, UsageCounterRepository

#: Bu fazın kota uyguladığı tek metrikler -- "llm_tokens"in henüz aralarında
#: olmama sebebi için modül docstring'ine bakın.
DOCUMENTS_METRIC = "documents"
DRAFTS_METRIC = "drafts"
#: Faz C3 (#187) -- her `POST /companies/{id}/training-runs` çağrısı başına
#: bir artış, dürüst çünkü bu endpoint bir eğitim koşusunun oluşturulduğu
#: tek yerdir (henüz bir arka plan/cron tetikleyicisi yok, bkz. #187'nin
#: gövdesi).
TRAINING_RUNS_METRIC = "training_runs"


def current_period(now: Optional[datetime] = None) -> str:
    """Mevcut takvim ayı kovası, `"YYYY-MM"`."""
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
        if metric == TRAINING_RUNS_METRIC:
            return quota.max_training_runs_per_month
        return None

    async def check_and_increment(self, company_id: str, metric: str, amount: int = 1) -> None:
        """`metric`'i `amount` kadar artırmak, `company_id`'nin mevcut ay için
        yapılandırılmış limitini aşacaksa hata fırlat; aksi halde kullanımı
        kaydet.

        Hiç `company_quotas` satırı olmayan bir şirket (varsayılan --
        satırlar yalnızca `PATCH .../quota` ile oluşturulur) sınırsızdır:
        kontrol şirket başına opt-in'dir, her şirketin sessizce miras
        aldığı bir varsayılan tavan değildir.

        Raises:
            RateLimitException: Limit ayarlanmışsa ve aşılacaksa. Yeni bir
                istisna türü yerine mevcut 429 istisna türünü yeniden
                kullanır -- bir kota, kavramsal olarak `app.api.rate_limit`
                zaten modellediği "çok fazla, çok hızlı (veya bu dönem çok
                fazla)" şekliyle aynıdır.
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
        """Kota uygulanan her metrik için mevcut dönemin kullanımı ile
        limiti -- `GET /companies/{id}/analytics/summary` içindir."""
        quota = await self.quota_repository.get(company_id)
        period = current_period()
        summary = {}
        for metric in (DOCUMENTS_METRIC, DRAFTS_METRIC, TRAINING_RUNS_METRIC):
            counter = await self.usage_repository.get(company_id, metric, period)
            summary[metric] = {
                "period": period,
                "used": counter.count if counter is not None else 0,
                "limit": self._limit_for(quota, metric),
            }
        return summary
