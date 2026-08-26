import logging
from typing import Any, Optional
from langfuse.langchain import CallbackHandler
from app.core.config import settings

logger = logging.getLogger(__name__)

_callback_handler: Optional[CallbackHandler] = None

def get_langfuse_callback() -> Optional[CallbackHandler]:
    """LangChain / LangGraph için Langfuse Callback Handler'ı alır veya başlatır."""
    global _callback_handler
    
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        logger.warning(
            "Langfuse tracking is disabled. "
            "Please configure LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to enable tracing."
        )
        return None
        
    if _callback_handler is None:
        try:
            import os
            if settings.LANGFUSE_PUBLIC_KEY:
                os.environ["LANGFUSE_PUBLIC_KEY"] = settings.LANGFUSE_PUBLIC_KEY
            if settings.LANGFUSE_SECRET_KEY:
                os.environ["LANGFUSE_SECRET_KEY"] = settings.LANGFUSE_SECRET_KEY
            if settings.LANGFUSE_HOST:
                os.environ["LANGFUSE_HOST"] = settings.LANGFUSE_HOST

            _callback_handler = CallbackHandler(
                public_key=settings.LANGFUSE_PUBLIC_KEY
            )
            logger.info("Langfuse callback handler initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Langfuse callback handler: {e}", exc_info=True)
            return None

    return _callback_handler


def build_trace_config(
    *,
    langfuse_user_id: Optional[str] = None,
    langfuse_session_id: Optional[str] = None,
    langfuse_tags: Optional[list[str]] = None,
    **configurable: Any,
) -> dict[str, Any]:
    """Bir LangGraph config'i oluşturur: verilen configurable anahtarlar artı Langfuse tracing.

    Daha önce ``ChatService``, ``DocumentService`` ve ``DraftService``
    içinde yaşayan üç özdeş private ``_trace_config`` kopyasının yerini
    alır.

    ``langfuse_*`` keyword-only parametreleri (yalnızca LangGraph'ın kendi
    node fonksiyonlarına ulaşan ``**configurable``'ın aksine)
    ``config["metadata"]`` haline gelir -- bu spesifik anahtar isimleri,
    ``langfuse-langchain`` callback handler'ının bir trace'i bir
    kullanıcı/session/etiket kümesine atfetmek için okuduğu isimlerdir
    (bkz. Faz 6 tenancy-plan bölümündeki şirket etiketli observability).
    Bir trace'i bu şekilde şirket kapsamına almak dürüst ama doğrulanmamış
    bir yaklaşımdır: ``compose.yml`` hâlâ ``langfuse`` v4 Python SDK
    bağımlılığına karşı ``langfuse/langfuse:2``'yi çalıştırıyor; bu repo'nun
    kendi önceki notları bu versiyon çiftini muhtemelen uyumsuz olarak
    zaten işaretlemiş durumda (v3+ kendi kendine barındırma bu projenin
    çalıştırmadığı ClickHouse/MinIO gerektirir) -- etiketleme eklemek ekstra
    bir maliyete sahip değildir ve tracing'in kendisi çalışmaya başladığı
    gün çalışmaya başlayacaktır, ama bugün doğrulanmış, her zaman açık
    observability hikayesi bu değil, ``runs``/``run_steps``/
    ``guardrail_events``'tir.

    Args:
        langfuse_user_id: Çağıranın id'si, biliniyorsa.
        langfuse_session_id: Varsa sohbet thread/session id'si.
        langfuse_tags: Serbest formatlı etiketler, ör. ``[f"company:{slug}",
            f"role:{role}"]`` -- ikisi de bilinmediğinde tamamen atla
            (sadece ``[]`` geçme), böylece boş bir liste handler'ın aksi
            halde çıkarabileceği gerçek bir listenin üzerine asla yazmaz.
        **configurable: ``config["configurable"]`` içine birleştirilen
            değerler (ör. ``thread_id``, ``status_queue``). Sade,
            sadece-tracing bir config için atla.

    Returns:
        LangGraph şeklinde bir config dict. Tracing hata fırlatmak yerine
        yok olma durumuna bozulur -- bir doküman yüklemesi veya bir sohbet
        turu, Langfuse'a ulaşılamadığı için başarısız olmamalıdır.
    """
    config: dict[str, Any] = {}
    if configurable:
        config["configurable"] = dict(configurable)

    handler = get_langfuse_callback()
    if handler:
        config["callbacks"] = [handler]

    metadata: dict[str, Any] = {}
    if langfuse_user_id:
        metadata["langfuse_user_id"] = langfuse_user_id
    if langfuse_session_id:
        metadata["langfuse_session_id"] = langfuse_session_id
    if langfuse_tags:
        metadata["langfuse_tags"] = langfuse_tags
    if metadata:
        config["metadata"] = metadata

    return config


def company_tags(company_id: Optional[str], role: Optional[str] = None) -> Optional[list[str]]:
    """`build_trace_config` için `["company:<slug>", "role:<role>"]`
    şeklindeki `langfuse_tags` listesini oluşturur; bilinmeyen yarıyı
    atlar -- ikisi de bilinmiyorsa `None` (`[]` değil), böylece çağıranlar
    bunu paylaşıldığı her (birkaç) çağrı noktasında ekstra bir `if`
    olmadan doğrudan geçirebilir.

    Burada veritabanını tekrar sorgulamak yerine
    `app.observability.company_metrics`'in zaten doldurulmuş slug
    önbelleğini (bkz. o modül) yeniden kullanır -- tracing bir isteğin
    ekstra bir sorgu ödemesinin nedeni asla olmamalıdır.
    """
    from app.observability import company_metrics

    tags: list[str] = []
    if company_id:
        slug = company_metrics.cached_slug(company_id) or company_id
        tags.append(f"company:{slug}")
    if role:
        tags.append(f"role:{role}")
    return tags or None
