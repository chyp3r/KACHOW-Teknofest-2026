"""Her sohbet turunun mesajlarının en iyi çaba (best-effort) ile kalıcı hale getirilmesi.

`ChatService`, hem normal bir istekten (`/chat/message`, `/chat/resume/sync`)
hem de SSE streaming endpoint'lerinden çağrılır; ikincisinde gerçek iş bir
async generator tarafından tüketilen arka plan `asyncio.create_task`'i
içinde gerçekleşir (bkz. `ChatService.handle_message_stream`). O görev
çalıştığında, herhangi bir `Depends(get_db)` session'ına sahip olan FastAPI
istek işleyicisi zaten `StreamingResponse` nesnesini döndürüp işini
bitirmiştir -- bu yüzden, `app.observability.run_recorder` ile aynı şekilde,
bu modül enjekte edilmiş bir session almak yerine her çağrı için kendi
kısa ömürlü session'ını açıp kapatır.

Her fonksiyon kendi istisnalarını yutar ve sadece loglar -- bir sohbet
turunu kaydetmek, o sohbet turunun başarısız olmasının nedeni olmamalıdır.
"""

import logging
from typing import Any, Optional

from app.core.config import settings
from app.domains.chat.repository import ChatMessageRepository, ChatSessionRepository
from app.infrastructure.database.session import tenant_session

logger = logging.getLogger(__name__)


async def record_turn(
    *,
    thread_id: str,
    user_id: Optional[str],
    document_id: Optional[str],
    user_message: str,
    user_details: Optional[dict[str, Any]] = None,
    reply: str,
    workflow_status: str,
    details: Optional[dict[str, Any]] = None,
    company_id: Optional[str] = None,
) -> None:
    """Tamamlanmış bir turu kalıcı hale getir: oturum satırı artı her iki mesajı.

    Args:
        thread_id: Birleştirilmiş checkpointer thread_id'si (bkz.
            `ChatService._thread_id`), `ChatSessionModel.id` olarak yeniden kullanılır.
        user_id: Bilindiği durumda, kimliği doğrulanmış çağıran.
        document_id: Varsa, bu tura eklenen belge.
        user_message: Çağıranın bu turdaki girdi metni.
        user_details: Çağıranın mesajında saklanan isteğe bağlı yapılandırılmış
            metadata. Devam (resume) turları, genel istek/yanıt sözleşmesini
            değiştirmeden cevaplanmış HITL formunu korumak için bunu kullanır.
        reply: Asistanın yanıt metni (veya kesintiye uğramış tur istemi).
        workflow_status: Bu tur için `ChatMessageResponse.workflow_status`.
        details: Bu tur için `ChatMessageResponse.details`, yalnızca asistan
            mesajında saklanır.
        company_id: Çağıranın kiracısı -- bu yazma işleminin, o tablolar
            buna geçirildiğinde `chat_sessions`/`chat_messages`'in
            satır düzeyi güvenlik (row-level-security) `WITH CHECK`'inden
            geçmesi için taşınır.
    """
    if not settings.CHAT_HISTORY_ENABLED:
        return
    try:
        async with tenant_session(company_id) as session:
            sessions = ChatSessionRepository(session)
            messages = ChatMessageRepository(session)
            await sessions.get_or_create(
                thread_id,
                user_id=user_id,
                company_id=company_id,
                document_id=document_id,
                title=_derive_title(user_message),
            )
            await messages.add_message(
                thread_id,
                role="user",
                content=user_message,
                details=user_details,
                company_id=company_id,
            )
            await messages.add_message(
                thread_id,
                role="assistant",
                content=reply,
                workflow_status=workflow_status,
                details=details,
                company_id=company_id,
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to record chat turn for thread %s", thread_id)


def _derive_title(user_message: str, max_length: int = 80) -> str:
    """Bir oturum listesi için ucuz bir görüntüleme etiketi -- LLM çağrısı içermez."""
    text = " ".join(user_message.split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"
