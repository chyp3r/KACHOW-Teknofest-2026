from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.core.enums.reasoning_level import ReasoningLevel


class ChatMessageRequest(BaseModel):
    """Yeni bir sohbet etkileşimi için istemci isteği."""

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
    draft_id: Optional[str] = Field(
        default=None,
        max_length=128,
        description=(
            "Opsiyonel olarak revize edilecek kayıtlı taslağın ID'si. Seçilen taslak, "
            "oturumun aktif taslak bağlamı olur. document_id ile birlikte gönderilemez."
        ),
    )
    reasoning_level: ReasoningLevel = Field(
        default=ReasoningLevel.BALANCED,
        description="Hız/kalite tercihi: fast (hızlı), balanced (dengeli, varsayılan), deep (derin muhakeme).",
    )

    @model_validator(mode="after")
    def validate_single_context(self) -> "ChatMessageRequest":
        if self.document_id and self.draft_id:
            raise ValueError("Aynı istekte yalnızca bir evrak veya bir taslak seçilebilir.")
        return self


class ChatMessageResponse(BaseModel):
    """Sohbet etkileşimi için orkestre edilmiş yanıt."""

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
    """İnsan-döngüde (human-in-the-loop) kapısında duraklatılmış bir sohbet çalışmasını devam ettirir.

    İki kesinti türü bu tek istek şeklini paylaşır: ``answer`` bir taslağın
    eksik bilgi yer tutucularını doldurur (Görev 2'nin "eksik bilgi talep
    etme" gereksinimi); ``approve``/``revise``/``reject``, birim yönlendirmeye
    geçmeden önce bir insanın onayına ihtiyaç duyan bir taslağı çözümler.
    """

    session_id: str = Field(
        min_length=1, max_length=128, description="Devam ettirilecek oturumun thread_id'si."
    )
    action: Literal["answer", "approve", "revise", "reject", "select"] = Field(
        description=(
            "answer: eksik bilgi/yazım briefi cevapları. approve/revise/reject: "
            "taslak onay kararı. reject aynı zamanda yazım briefi kapısını da iptal eder. "
            "select: transfer akışında alıcı belirsizliğini çözen seçim (bkz. "
            "artifact_transfer_disambiguate, answers.recipient_id)."
        )
    )
    answers: dict[str, str | list[str]] = Field(
        default_factory=dict,
        description=(
            "action='answer' için PromptQuestion.key -> kullanıcı cevabı eşlemesi. "
            "Çoklu seçim soruları bir liste taşır; her başka soru tek bir dizedir "
            "(\"Sen karar ver\" seçeneği dahil, bkz. writing_brief.AUTO_ANSWER). "
            "action='select' için answers.recipient_id, seçilen adayın kullanıcı id'si."
        ),
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
