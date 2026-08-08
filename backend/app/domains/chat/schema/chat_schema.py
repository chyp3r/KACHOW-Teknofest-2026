from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.core.enums.reasoning_level import ReasoningLevel


class ChatMessageRequest(BaseModel):
    """Client request for a new chat interaction."""

    message: str = Field(
        min_length=1, max_length=8000, description="Kullanıcının gönderdiği mesaj veya istek."
    )
    session_id: Optional[str] = Field(
        default=None,
        max_length=128,
        pattern=r"^[A-Za-z0-9:_-]+$",
        description=(
            "Opsiyonel oturum/sohbet kimliği. LangGraph checkpointer'ında thread_id "
            "olarak kullanılır: hem konuşma geçmişini hem de bekleyen bir insan-onayı "
            "kesintisini bu kimlik üzerinden taşır. Belirtilmezse sunucu bir tane üretir "
            "ve ilk SSE olayında (session) geri döner."
        ),
    )
    document_id: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Opsiyonel olarak hakkında soru sorulan spesifik belgenin (storage_path) ID'si.",
    )
    reasoning_level: ReasoningLevel = Field(
        default=ReasoningLevel.BALANCED,
        description="Hız/kalite tercihi: fast (hızlı), balanced (dengeli, varsayılan), deep (derin muhakeme).",
    )


class ChatMessageResponse(BaseModel):
    """Orchestrated response for the chat interaction."""

    reply: str = Field(
        description="Kullanıcıya gösterilecek olan nihai metin/mesaj yanıtı."
    )
    workflow_status: str = Field(
        description="Çalıştırılan iş akışının genel durumu (örn. COMPLETED, FAILED, INTERRUPTED)."
    )
    session_id: str = Field(
        description="Bu çalışmanın thread_id'si; devam (resume) çağrılarında kullanılır."
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Arka planda çalışan alt iş akışlarına (RAG, Draft, Classification vb.) ait detaylı sonuçlar.",
    )


class ChatResumeRequest(BaseModel):
    """Resume a chat run paused at the human-in-the-loop gate.

    Two interrupt kinds share this one request shape: ``answer`` fills in a
    draft's missing-information placeholders (Görev 2's "eksik bilgi talep
    etme" requirement); ``approve``/``revise``/``reject`` resolve a draft
    that needed a human's sign-off before proceeding to unit routing.
    """

    session_id: str = Field(
        min_length=1, max_length=128, description="Devam ettirilecek oturumun thread_id'si."
    )
    action: Literal["answer", "approve", "revise", "reject"] = Field(
        description="answer: eksik bilgi cevapları. approve/revise/reject: taslak onay kararı."
    )
    answers: dict[str, str] = Field(
        default_factory=dict,
        description="action='answer' için InfoQuestion.key -> kullanıcı cevabı eşlemesi.",
    )
    instructions: str = Field(
        default="", max_length=4000, description="action='revise' için ek talimat."
    )
    reason: str = Field(
        default="", max_length=2000, description="action='reject' için red gerekçesi."
    )
    reasoning_level: Optional[ReasoningLevel] = Field(
        default=None,
        description=(
            "action='revise' için bu tekrar denemede kullanılacak seviye. "
            "Belirtilmezse oturumun mevcut seviyesi korunur."
        ),
    )
