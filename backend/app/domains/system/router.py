import asyncio
import logging

import httpx
from fastapi import APIRouter, Query, Response

from app.api.responses import SuccessResponse
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])
health_router = APIRouter(tags=["health"])

#: Per-dependency probe budget. A slow dependency should show up as "down" in
#: a bounded time, not hang the health check itself.
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


@health_router.get("/health")
async def health_check(response: Response, deep: bool = Query(default=False)):
    """Health check endpoint returning standardized APIResponse.

    Args:
        deep: When True, probes Postgres, Redis, Qdrant, Ollama and the
            LangGraph checkpointer instead of only reporting that the process
            is up. Any failed dependency sets the HTTP status to 503 so
            uptime monitors and load balancers can act on it, not just read it.
    """
    data = {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
    }

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

        if any(status == "fail" for status in dependencies.values()):
            data["status"] = "degraded"
            response.status_code = 503

    return SuccessResponse(data=data)
