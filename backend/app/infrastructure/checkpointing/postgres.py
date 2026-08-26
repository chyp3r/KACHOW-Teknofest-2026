"""Süreç geneli LangGraph checkpointer yaşam döngüsü.

``AsyncPostgresSaver.from_conn_string()`` düz bir constructor değil,
eşzamansız bir context manager'dır -- bağlam çıkar çıkmaz sökülen bir
bağlantı havuzuna sahiptir. Bunu await edip atmak (naif yaklaşım), havuzu
ilk checkpoint yazımından önce kapatırdı. Bunun yerine bağlam bir kez
girilir, sürecin ömrü boyunca bir :class:`~contextlib.AsyncExitStack` içinde
açık tutulur, ve kapatma sırasında açıkça kapatılır.

``app.lifespan``'e uygun şekilde bilinçli olarak en iyi çaba: eksik veya
ulaşılamayan bir Postgres, veya checkpoint paketlerinin kurulu olmaması,
API'nin başlamasını engellememelidir. ``get_checkpointer()``'ın ``None``
döndürmesi, planlama grafiğinin onsuz derlendiği anlamına gelir -- Görev 1
ve Görev 2'nin kesinti-dışı yarısı çalışmaya devam eder; yalnızca insan
döngüde (eksik bilgi istekleri, taslak onayı) kullanılamaz hale gelir.
"""

import logging
from contextlib import AsyncExitStack
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_stack: Optional[AsyncExitStack] = None
_saver: Optional[Any] = None


async def init_checkpointer() -> Optional[Any]:
    """Checkpointer'ın bağlantı havuzunu aç ve şema kurulumunu çalıştır.

    Planlama grafiği derlenmeden önce çağrılmalıdır, çünkü checkpointer
    ``StateGraph.compile(checkpointer=...)``'e geçirilir.

    Returns:
        Hazır :class:`AsyncPostgresSaver`, veya checkpointing devre dışıysa
        ya da kullanılamıyorsa ``None``.
    """
    global _stack, _saver

    if not settings.CHECKPOINTER_ENABLED:
        logger.info("Checkpointer disabled via settings; HITL is unavailable.")
        return None

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError:
        logger.warning(
            "langgraph-checkpoint-postgres is not installed; HITL is unavailable."
        )
        return None

    stack = AsyncExitStack()
    try:
        saver = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(settings.checkpointer_dsn)
        )
        # İdempotent: checkpointer'ın önceki bir çalıştırmada zaten kurduğu
        # bir veritabanına karşı olanlar dahil, her başlangıçta çalıştırmak güvenlidir.
        await saver.setup()
    except Exception:
        logger.warning(
            "Failed to initialise the LangGraph checkpointer; HITL is unavailable.",
            exc_info=True,
        )
        await stack.aclose()
        return None

    _stack = stack
    _saver = saver
    logger.info("LangGraph checkpointer ready.")
    return _saver


async def close_checkpointer() -> None:
    """Checkpointer'ın bağlantı havuzunu kapat. Hiç açılmadıysa çağırmak güvenlidir."""
    global _stack, _saver
    if _stack is not None:
        await _stack.aclose()
    _stack = None
    _saver = None


def get_checkpointer() -> Optional[Any]:
    """Süreç geneli checkpointer'ı döndür, veya kullanılamıyorsa ``None``."""
    return _saver
