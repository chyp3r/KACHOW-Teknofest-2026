from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class GuardrailEventModel(Base, TimestampMixin):
    """Denetim için tutulan tek bir input veya output guardrail kararı.

    ``RunModel``/``RunStepModel`` (``app.observability.model.
    run_model``) ile kardeş: isteğe bağlı Langfuse tracer'dan bağımsız,
    "her zaman açık, birinci taraf denetim kaydı" rolünün, özellikle
    guardrail kararları için karşılığı. "Asistan söylememesi gereken bir
    şey söyledi" diyen bir kullanıcının "guardrail ne gördü ve ne karar
    verdi" sorusuna, isteğin ömrünü aşan ve üçüncü taraf bir tracing
    hesabının yapılandırılmış olmasına bağlı olmayan bir yanıta ihtiyacı
    vardır.

    ``run_id``/``document_id`` her ikisi de nullable ve birbirinden
    bağımsızdır: yükleme anındaki bir PII/hassasiyet bulgusunun bir
    ``document_id``'si vardır ama henüz ``run_id``'si yoktur (onu okuyan
    sohbet turu -eğer olursa- daha sonra gelir); bir assist yanıtındaki
    output-gate kararının bir ``run_id``'si ve fiilen yararlandığı
    ``related_document_ids`` listesi vardır.
    """

    __tablename__ = "guardrail_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: `0016_recorder_tables_rls` migration'ından beri NOT NULL -- graph
    #: içindekiler dahil `PlanningState.company_id` üzerinden her çağrı
    #: noktası tarafından doldurulur (bkz. `RunModel.company_id`'nin
    #: docstring'i).
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("runs.id"), nullable=True, index=True
    )
    document_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    #: "input" | "output".
    stage: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: "pii" | "sensitivity" | "injection" | "magic_byte" | "archive_bomb" |
    #: "groundedness" | "leakage" | "llm_judge".
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: "passed" | "flagged" | "blocked" | "redacted" | "needs_review".
    decision: Mapped[str] = mapped_column(String, nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    #: Kısa, insan tarafından okunabilir sebep metinleri -- kararı tetikleyen
    #: ham hassas değer asla değil (bkz. tam olarak bu sebeple sadece
    #: sansürlenmiş bir önizleme taşıyan ``app.ai.guardrails.pii.PiiFinding``).
    reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    #: Kim soruyordu ve hangi yetki seviyesindeydi -- bir sızıntı önleme
    #: engelinin denetiminin fiilen yanıtlanmasını gerektirdiği sorular.
    requester_user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    requester_role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    effective_clearance: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: Bir yanıt tek turda birden fazla dokümandan yararlanabilir; sadece
    #: biri geçerli olsa bile bu alan liste olarak kalır, böylece şekli
    #: hiç değişmek zorunda kalmaz.
    related_document_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: Bu karar için fiilen kullanılan Ollama model etiketi (ör.
    #: ``settings.OLLAMA_MODEL``'den) ve bunu üreten prompt şablonunun
    #: diskteki hangi revizyonu (``PromptManager``'ın şablon başına
    #: versiyonu) -- birlikte, "bu karar bugün tekrar üretilir miydi"
    #: sorusunu yanıtlar.
    llm_model_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    prompt_template_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
