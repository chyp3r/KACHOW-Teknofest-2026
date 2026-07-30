from pydantic import BaseModel, Field
from typing import Any, Optional


class ChatMessageRequest(BaseModel):
    """Client request for a new chat interaction."""

    message: str = Field(description="Kullanıcının gönderdiği mesaj veya istek.")
    session_id: Optional[str] = Field(
        default=None, description="Opsiyonel oturum/sohbet kimliği (geçmiş takibi için)."
    )
    document_id: Optional[str] = Field(
        default=None, description="Opsiyonel olarak hakkında soru sorulan spesifik belgenin (storage_path) ID'si."
    )


class ChatMessageResponse(BaseModel):
    """Orchestrated response for the chat interaction."""

    reply: str = Field(
        description="Kullanıcıya gösterilecek olan nihai metin/mesaj yanıtı."
    )
    workflow_status: str = Field(
        description="Çalıştırılan iş akışının genel durumu (örn. COMPLETED, FAILED)."
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Arka planda çalışan alt iş akışlarına (RAG, Draft, Classification vb.) ait detaylı sonuçlar.",
    )
