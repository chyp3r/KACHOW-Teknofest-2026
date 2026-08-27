"""Uygulama başlatma ve kapatma kancaları.

Eskiden ilk isteği gönderen şanssız kullanıcının ödediği pahalı, tek seferlik iş
artık burada yapılıyor: modelleri Ollama'ya yüklemek ve LangGraph iş akışlarını
derlemek. 

Her adım best-effort'tur (en iyi çabayla). Eksik bir Ollama veya erişilemeyen bir
Qdrant, API'nin ayağa kalkmasını engellememelidir -- süreç import zamanında ölmek
yerine health endpoint'i ayağa kalkmalı ve sorunu raporlamalıdır.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Başlangıç ısınması için üst sınır. Bunun ötesinde API yine de ayağa kalkmalı
#: ve kalan kısmı ilk isteğe ödettirmelidir.
WARMUP_TIMEOUT_SECONDS = 120

#: Havuz doygunluğu bu oranı geçtiğinde INFO yerine WARNING loglanır.
_POOL_WARN_RATIO = 0.8


async def _monitor_db_pool() -> None:
    """DB bağlantı havuzunun doygunluğunu periyodik loglar.

    ``settings.DB_POOL_MONITOR_INTERVAL_SECONDS`` saniyede bir çalışır (0
    ise hiç başlatılmaz -- bkz. ``lifespan``). Kullanılan bağlantı oranı
    ``_POOL_WARN_RATIO``'yu geçtiğinde WARNING loglar; #288'deki gibi bir
    tükenme, sessizce zaman aşımlarına dönüşmeden önce burada görünür.
    """
    from app.infrastructure.database.session import pool_status

    interval = settings.DB_POOL_MONITOR_INTERVAL_SECONDS
    while True:
        await asyncio.sleep(interval)
        try:
            stats = pool_status()
            in_use = stats["checkedout"]
            capacity = stats["capacity"] or 1
            ratio = in_use / capacity
            level = logging.WARNING if ratio >= _POOL_WARN_RATIO else logging.INFO
            logger.log(
                level,
                "db_pool_status checkedout=%d capacity=%d ratio=%.2f "
                "size=%d checkedin=%d overflow=%d",
                in_use,
                stats["capacity"],
                ratio,
                stats["size"],
                stats["checkedin"],
                stats["overflow"],
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("db_pool_status probe failed", exc_info=True)


async def _warm_up_models() -> None:
    """Yapılandırılmış modelleri Ollama'nın belleğine yükler."""
    from app.ai.llms import get_fast_llm_client, get_llm_client

    clients = [get_llm_client()]
    fast = get_fast_llm_client()
    if fast is not clients[0]:
        clients.append(fast)

    for client in clients:
        warm_up = getattr(client, "warm_up", None)
        if warm_up is None:
            continue
        await warm_up()


async def _warm_up_graphs() -> None:
    """Trafik gelmeden önce iş akışlarını derler ve retriever'ları oluşturur."""
    from app.api.dependency import (
        get_document_analysis_graph,
        get_document_analysis_mevzuat_retriever,
        get_draft_graph,
        get_mevzuat_retriever,
        get_planning_graph,
        get_rag_graph,
        get_routing_graph,
    )

    local_retriever = await get_mevzuat_retriever()
    analysis_retriever = await get_document_analysis_mevzuat_retriever(local_retriever)
    analysis_graph = await get_document_analysis_graph(analysis_retriever)
    rag_graph = await get_rag_graph()
    draft_graph = await get_draft_graph()
    routing_graph = await get_routing_graph()
    await get_planning_graph(analysis_graph, rag_graph, draft_graph, routing_graph)

    # Bu modüldeki her adım gibi best-effort: yalnızca MEVZUAT_SOURCE="mcp"
    # bir FallbackMevzuatRetriever oluşturduğunda mevcuttur (bkz.
    # get_document_analysis_mevzuat_retriever); düz bir HybridRetriever'ın
    # (yerel mod) hiç warm-up adımı yoktur. _startup() içindeki bu fonksiyonun
    # kendi best-effort gather'ı içinde çalışır, böylece yavaş veya erişilemez
    # bir MCP sunucusu, canlı kaynağın devreye girmesini geciktirir ama
    # başlangıcı engellemez veya başarısız kılmaz -- bu sırada gelen her istek
    # zaten zarif olan fallback'i kullanır.
    warm_up = getattr(analysis_retriever, "warm_up", None)
    if warm_up is not None:
        await warm_up()

    logger.info("Compiled all AI workflows.")


async def _startup() -> None:
    """Bireysel hatalara tolerans göstererek her ısınma adımını çalıştırır."""
    tasks = [_warm_up_graphs()]
    if settings.OLLAMA_WARMUP_ON_STARTUP:
        tasks.append(_warm_up_models())

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=WARMUP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Startup warm-up exceeded %ss; continuing without it.",
            WARMUP_TIMEOUT_SECONDS,
        )
        return

    for result in results:
        if isinstance(result, Exception):
            logger.warning("A startup warm-up step failed: %s", result)


def _require_auth_in_production() -> None:
    """Kimlik doğrulaması açık bırakılmış bir production dağıtımının ayağa
    kalkmasını reddeder.

    /chat ve /documents, istek başına onlarca saniye boyunca yerel bir modeli
    meşgul eder ve kendisine verilen storage_path/session_id her ne ise onu
    okur (bkz. settings.REQUIRE_AUTH'un docstring'i) -- yarışma demosu bir
    login akışı olmadan çalışsın diye varsayılan olarak açıktır, ancak gerçek
    bir "production" dağıtımının bu şekilde bırakılması, bu aşamanın kapatmayı
    amaçladığı IDOR açığıdır. Ayağa kalkmayı reddetmek kasıtlıdır: REQUIRE_AUTH
    değerini değiştirmek çok kolaydır ve bir log satırı kolayca gözden
    kaçabilir, ama hiç başlamamış bir süreç kaçmaz.

    Raises:
        RuntimeError: `ENVIRONMENT == "production"` ise ve `REQUIRE_AUTH`
            etkin değilse.
    """
    if settings.ENVIRONMENT == "production" and not settings.REQUIRE_AUTH:
        raise RuntimeError(
            "REQUIRE_AUTH must be enabled when ENVIRONMENT=production -- "
            "set REQUIRE_AUTH=true or run with ENVIRONMENT=development/staging."
        )


#: Settings.SECRET_KEY'nin kendi varsayılanı; bu koruma ile alan tanımının
#: sessizce birbirinden ayrışmaması için modül sabiti olarak tutulur.
_DEFAULT_SECRET_KEY = "supersecretkeychangeinproduction"


def _require_secret_key_in_production() -> None:
    """Varsayılan SECRET_KEY ile bir production dağıtımının ayağa kalkmasını
    reddeder.

    SECRET_KEY her access/refresh JWT'yi imzalar (bkz. app.core.security);
    yayınlanan varsayılan değer herkese açıktır (bu deponun kendi kaynak
    kodunda yer alır), bu yüzden onu production'da olduğu gibi bırakmak
    herkesin imzaladığı token'ları kabul etmekle eşdeğerdir. Yukarıdaki
    _require_auth_in_production() ile aynı yapıda ve aynı sebeple: yanlış
    bir varsayılan değer bir log satırında kolayca gözden kaçabilir, ama hiç
    başlamamış bir süreç kaçmaz.

    Raises:
        RuntimeError: `ENVIRONMENT == "production"` ise ve `SECRET_KEY` hâlâ
            yayınlanan varsayılan değerdeyse.
    """
    if settings.ENVIRONMENT == "production" and settings.SECRET_KEY == _DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY must be changed from its default when "
            "ENVIRONMENT=production -- set a unique SECRET_KEY or run with "
            "ENVIRONMENT=development/staging."
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Uygulama başlatma ve kapatmayı yönetir.

    Args:
        app: FastAPI uygulaması.

    Yields:
        Kontrolü çalışan uygulamaya devreder.
    """
    logger.info("Starting %s (%s)...", settings.PROJECT_NAME, settings.ENVIRONMENT)

    _require_auth_in_production()
    _require_secret_key_in_production()

    # Import'un yan etkisi olarak event bus'ın dinleyicilerini kaydeder
    # (@subscribe dekoratörü modül yüklenirken çalışır). Bu import olmadan
    # DocumentService/DraftService'in publish() çağrılarının hiçbir
    # dinleyicisi olmaz -- bus yalnızca yazma amaçlı kalırdı.
    import app.events.subscribers  # noqa: F401

    # Yapılandırılmışsa harici MCP sunucuları. Varsayılan olarak hiçbir şey
    # yapmaz: MEVZUAT_MCP_ENABLED ayarlanmadıkça mevzuat sunucusu kapalıdır
    # ve burada ona hiçbir şey temas etmez -- kayıt yalnızca nasıl
    # başlatılacağını kaydeder, bu yüzden eksik veya erişilemeyen bir sunucu
    # bir araç gerçekten çağrılana kadar hiçbir şeye mal olmaz.
    from app.mcp.registry import register_servers

    register_servers()

    # Kasıtlı olarak _startup()'ın WARMUP_TIMEOUT_SECONDS bütçesinin dışında:
    # planlama grafiğinin derlemesi (_warm_up_graphs içinde) checkpointer'ın
    # zaten açık olmasını gerektirir ve yavaş bir Postgres, model ısınma
    # bütçesinden sessizce zaman çalmamalı veya bu bütçe tarafından atlanmamalıdır.
    from app.infrastructure.checkpointing import init_checkpointer

    await init_checkpointer()

    # Buradaki her adım gibi best-effort: bir seed hatası API'nin ayağa
    # kalkmasını engellememelidir. Checkpointer'dan sonra yerleştirilmiştir
    # (böylece veritabanının erişilebilir olduğu bilinir) ve
    # _startup()'ın ısınma bütçesinin dışındadır, init_checkpointer()'ın
    # kendisiyle aynı gerekçeyle.
    #
    # Sıra önemlidir: demo şirketi, altında seed edilen kullanıcıların ve
    # birimlerin onun id'sine referans verebilmesi için önce var olmalıdır
    # (bkz. app.domains.companies.seeder'ın kendi docstring'i).
    from app.domains.companies.seeder import seed_demo_company

    demo_company_id = await seed_demo_company()

    from app.domains.users.seeder import seed_default_users

    await seed_default_users(demo_company_id)

    if demo_company_id is not None:
        from app.domains.units.seeder import seed_default_units

        await seed_default_units(demo_company_id)

    await _startup()

    pool_monitor_task: "asyncio.Task | None" = None
    if settings.DB_POOL_MONITOR_INTERVAL_SECONDS > 0:
        pool_monitor_task = asyncio.create_task(_monitor_db_pool())

    logger.info("Startup complete; accepting requests.")
    try:
        yield
    finally:
        logger.info("Shutting down %s.", settings.PROJECT_NAME)
        if pool_monitor_task is not None:
            pool_monitor_task.cancel()
            try:
                await pool_monitor_task
            except (asyncio.CancelledError, Exception):
                pass
        from app.infrastructure.checkpointing import close_checkpointer

        await close_checkpointer()
