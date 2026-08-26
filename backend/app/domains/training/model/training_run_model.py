from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class TrainingRunModel(Base, TimestampMixin):
    """Bir şirket için eğitim hattının bir çalıştırması.

    Faz C3 (#187) bugün yalnızca `kind="style_adapter"` satırları üretir --
    `app.domains.companies.provider.set_company_adapter`'ın
    `CompanyAdapter`'ını güncelleyen deterministik-diff + tek-LLM-çağrısı
    yolu. `kind`, `"lora_sft"`/`"lora_dpo"` (gelecekteki, GPU destekli bir
    faz, bilerek burada kapsam dışı -- bkz. #187'nin kendi gövdesi) bir
    migration olmadan eklenebilsin diye gevşek bir string olarak kalır
    (enum değil), `FeedbackModel.target_kind` ile aynı kural.

    `artifact_path` de benzer şekilde bu fazın ürettiği hiçbir çalıştırma
    tarafından kullanılmaz (bir stil adaptörü bir dosyada değil,
    `CompanyModel.settings`'te yaşar) ama LoRA fazının daha sonra bir şema
    değişikliğine ihtiyaç duymaması için şimdiden tabloda tutulur.
    """

    __tablename__ = "training_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    #: Bugün "style_adapter"; "lora_sft" / "lora_dpo" ileriye ayrılmıştır.
    kind: Mapped[str] = mapped_column(String, nullable=False)
    #: "queued" | "running" | "succeeded" | "failed" | "skipped" -- "skipped"
    #: `MIN_FEEDBACK_SAMPLES`'ın altında kalma sonucudur, bir hata değildir.
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    triggered_by: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    #: Bugün "manual"; "scheduled" gelecekteki bir cron tetikleyicisi için ayrılmıştır.
    trigger: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    sample_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: örn. `{"liked_count": ..., "disliked_count": ..., "adapter_version": ...}`.
    metrics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    artifact_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
