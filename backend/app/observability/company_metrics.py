"""Şirket etiketli, kasıtlı olarak küçük tutulan Prometheus toplayıcı kümesi
-- kiracılık planının kendi kardinalite uyarısı burada da geçerli:
`app.observability.ai_metrics`'in ~20 toplayıcısı zaten `graph x node x
status` çarpımını yapıyor ve bunu büyüyen, hiç küçülmeyen bir şirket slug
kümesiyle çarpmak, silinmiş şirketler için bile seri sayısını kalıcı olarak
şişirir. Bu modül, o maliyete değecek yalnızca birkaç şirket düzeyinde iş
sinyaliyle sınırlı tutulur; etiket değeri her zaman insan tarafından
okunabilir `slug`'dır (uuid `id` değil), bu da bir Grafana panosu izleyicisinin
`company` şablon değişkenine gerçekte ne yazacağıyla eşleşir.

`kachow_company_requests_total` kasıtlı olarak tek etiketlidir (yalnızca
`company`, `endpoint_group` yok) -- bir isteği bir rota grubuna atfetmek ya
rota başına enstrümantasyon ya da ikinci bir middleware geçişinden eşleşen
rota durumunu okumayı gerektirir; bu modülün bütün amacı ucuz ve basit
kalmaktır. Mevcut genel HTTP metrikleri (`app.observability.metrics`,
şirkete göre etiketlenmemiş) rota başına dökümü zaten kapsıyor.
"""

import logging
from typing import Optional

from prometheus_client import Counter, Gauge

logger = logging.getLogger(__name__)

COMPANY_REQUESTS = Counter(
    "kachow_company_requests_total",
    "Authenticated requests, by company.",
    ["company"],
)

COMPANY_DOCUMENTS = Counter(
    "kachow_company_documents_total",
    "Documents registered, by company.",
    ["company"],
)

COMPANY_DRAFTS = Counter(
    "kachow_company_drafts_total",
    "Draft versions created, by company and status.",
    ["company", "status"],
)

COMPANY_GUARDRAIL_BLOCKS = Counter(
    "kachow_company_guardrail_blocks_total",
    "Guardrail deny/block decisions, by company and kind.",
    ["company", "kind"],
)

#: `AnalyticsService.summary` bir şirket için her çalıştığında fırsatçı bir
#: şekilde yenilenir (bkz. o modül), sürekli bir zamanlayıcıyla değil -- bu
#: kod tabanında onu çalıştıracak periyodik görev çalıştırıcısı yok
#: (celery/cron yok; bkz. `app.lifespan`'ın yalnızca başlangıç kapsamı), bu
#: yüzden bu gauge'un değeri o şirket için yapılan son analitik özet isteği
#: kadar günceldir. Yine de dürüsttür: uydurma bir sürekli sinyal değil,
#: gerçekte en son ölçtüğü şeyi bildirir.
COMPANY_ACTIVE_USERS = Gauge(
    "kachow_company_active_users",
    "Users active in the last 7 days, by company (refreshed on each analytics summary call).",
    ["company"],
)

#: company_id -> slug. `resolve_slug` tarafından tembelce doldurulur, hiç
#: tahliye edilmez -- bir şirketin slug'ı oluşturulduktan sonra değişmez
#: (bkz. `CompanyModel.slug`'ın kendi docstring'i), bu yüzden "kaç şirket
#: varsa o kadar" ile sınırlı, kalıcı olarak büyüyen bir önbellek güvenlidir;
#: `documents/service.py`'nin `_qa_vector_size` süreç başına bir kez sorgula
#: önbelleğinin zaten dayandığı aynı gerekçe.
_slug_cache: dict[str, str] = {}


def cache_slug(company_id: str, slug: str) -> None:
    """Bilinen bir `company_id` -> `slug` eşleşmesini kaydet, örn.
    `CompanyRepository.get_by_id` satırı başka bir nedenle zaten
    yüklediği anda -- yalnızca metrik etiketi için ikinci bir sorgulamayı
    önler."""
    _slug_cache[company_id] = slug


def cached_slug(company_id: Optional[str]) -> Optional[str]:
    """`company_id` için önbelleğe alınmış slug, ya da önbellek ıskalarsa `None`.

    Kasıtlı olarak veritabanını kendisi sorgulamaz -- bu modül her yerden
    (zaten çok şey import eden `app.api.dependency` dahil) import
    edilebilsin diye DB bağımlılığından bağımsız kalmalıdır. Bir sorgulamayı
    karşılayabilen çağıranlar (elinde zaten bir `CompanyRepository` olanlar,
    örn. `get_current_user`) cevabı aldıklarında `cache_slug`'ı çağırmalıdır.
    """
    if company_id is None:
        return None
    return _slug_cache.get(company_id)


def note_request(company_id: Optional[str]) -> None:
    """Slug'ı zaten önbelleğe alınmışsa `company_id` için `COMPANY_REQUESTS`'i
    artır. Bir önbellek ıskası (şirketin slug'ı bu süreçte hiç çözümlenmedi)
    bir sorgulamayı tetiklemek yerine sessizce atlanır -- bkz.
    `cached_slug`'ın docstring'i."""
    slug = cached_slug(company_id)
    if slug is not None:
        COMPANY_REQUESTS.labels(company=slug).inc()


def note_document_registered(company_slug: str) -> None:
    COMPANY_DOCUMENTS.labels(company=company_slug).inc()


def note_draft_created(company_slug: str, status: Optional[str]) -> None:
    COMPANY_DRAFTS.labels(company=company_slug, status=status or "unknown").inc()


def note_guardrail_block(company_slug: str, kind: str) -> None:
    COMPANY_GUARDRAIL_BLOCKS.labels(company=company_slug, kind=kind).inc()


def set_active_users(company_slug: str, count: int) -> None:
    COMPANY_ACTIVE_USERS.labels(company=company_slug).set(count)


def init_company_metrics() -> None:
    """Toplayıcılarının Prometheus'a kaydolması için bu modülün import
    edilmesini zorla.

    `app.observability.ai_metrics.init_ai_metrics` ile simetriktir --
    buradaki her toplayıcı modül import zamanında zaten kendini kaydediyor
    olsa bile, bunun neden açık ve grep'lenebilir bir çağrı noktası olarak
    var olduğu için o fonksiyonun kendi docstring'ine bakın.
    """
    logger.debug("Company metrics registered.")
