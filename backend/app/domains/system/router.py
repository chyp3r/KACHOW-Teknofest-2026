import asyncio
import logging

import httpx
from fastapi import APIRouter, Query, Response

from app.api.responses import SuccessResponse
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])
health_router = APIRouter(tags=["health"])

#: Bağımlılık başına yoklama bütçesi. Yavaş bir bağımlılık, health check'i
#: askıda bırakmak yerine sınırlı bir sürede "down" olarak görünmelidir.
_PROBE_TIMEOUT_SECONDS = 2.0


async def _probe_postgres() -> str:
    from app.infrastructure.database.session import verify_db_connection

    try:
        ok = await asyncio.wait_for(verify_db_connection(), timeout=_PROBE_TIMEOUT_SECONDS)
        return "ok" if ok else "fail"
    except Exception:
        return "fail"


async def _probe_redis() -> str:
    from app.infrastructure.cache import get_cache

    try:
        cache = get_cache()
        await asyncio.wait_for(cache.connect(), timeout=_PROBE_TIMEOUT_SECONDS)
        await asyncio.wait_for(cache.client.ping(), timeout=_PROBE_TIMEOUT_SECONDS)
        return "ok"
    except Exception:
        return "fail"


async def _probe_qdrant() -> str:
    from app.infrastructure.vectorstore import get_vector_store

    try:
        store = get_vector_store()
        await asyncio.wait_for(store.client.get_collections(), timeout=_PROBE_TIMEOUT_SECONDS)
        return "ok"
    except Exception:
        return "fail"


async def _probe_ollama() -> str:
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            response.raise_for_status()
        return "ok"
    except Exception:
        return "fail"


def _probe_checkpointer() -> str:
    from app.infrastructure.checkpointing import get_checkpointer

    if not settings.CHECKPOINTER_ENABLED:
        return "disabled"
    return "ok" if get_checkpointer() is not None else "fail"


def _probe_router_semantic() -> str:
    """Niyet merdiveninin semantik basamağının fiilen yüklenip yüklenmediği.

    ``_probe_checkpointer`` gibi bilgilendirme amaçlıdır -- genel sağlık
    durumunu asla 503'e çevirmemesi için ``dependencies`` dışında raporlanır.
    Eski veya eksik bir prototip vektör dosyası router'ı zayıflatır (bkz.
    ``ROUTER_SEMANTIC_AVAILABLE``'ın docstring'i) ama sistem yine de her
    isteği yanıtlar; sadece merdivenin bir basamağı eksik olarak yapar.
    """
    from app.observability.ai_metrics import router_semantic_available

    return "ok" if router_semantic_available() else "unavailable"


async def build_health_payload(deep: bool) -> tuple[dict, bool]:
    """HTTP yanıt sarmalamasından bağımsız olarak health check'in gerçek
    verisi -- `health_check` (bunu, çağıranın değer okuyabileceği bir
    özelliği olmayan bir ``JSONResponse`` olan ``SuccessResponse`` içine
    saran rota) ile ``app.domains.companies.root_router.root_health``
    (kendi şirket bazlı bölümünü içine birleştirmek için render edilmiş bir
    yanıt değil, ham dict'e ihtiyaç duyan) tarafından paylaşılır.

    Returns:
        `(data, degraded)` -- derinlemesine yoklanan herhangi bir bağımlılık
        başarısız olduysa `degraded` `True`'dur, çağıranın kendi durum kodunu
        belirlemesi içindir.
    """
    data = {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
    }
    degraded = False

    if deep:
        postgres, redis_status, qdrant, ollama = await asyncio.gather(
            _probe_postgres(), _probe_redis(), _probe_qdrant(), _probe_ollama()
        )
        dependencies = {
            "postgres": postgres,
            "redis": redis_status,
            "qdrant": qdrant,
            "ollama": ollama,
        }
        data["dependencies"] = dependencies
        data["checkpointer"] = _probe_checkpointer()
        data["router_semantic"] = _probe_router_semantic()

        # Bilgilendirme amaçlı (durumu asla 503'e çevirmez): SQLAlchemy
        # bağlantı havuzunun anlık doygunluğu -- #288'deki gibi bir
        # tükenmeyi teşhis etmeyi kolaylaştırır.
        from app.infrastructure.database.session import pool_status

        try:
            data["db_pool"] = pool_status()
        except Exception:
            data["db_pool"] = None

        if any(status == "fail" for status in dependencies.values()):
            data["status"] = "degraded"
            degraded = True

    return data, degraded


@health_router.get("/health")
async def health_check(response: Response, deep: bool = Query(default=False)):
    """Standartlaştırılmış bir APIResponse döndüren sağlık kontrolü uç noktası.

    Args:
        deep: True olduğunda, yalnızca sürecin ayakta olduğunu bildirmek
            yerine Postgres, Redis, Qdrant, Ollama ve LangGraph checkpointer'ı
            yoklar. Başarısız olan herhangi bir bağımlılık, uptime izleme
            araçlarının ve yük dengeleyicilerin sadece okumakla kalmayıp
            harekete geçebilmesi için HTTP durumunu 503 yapar.
    """
    data, degraded = await build_health_payload(deep)
    if degraded:
        response.status_code = 503
    return SuccessResponse(data=data)
