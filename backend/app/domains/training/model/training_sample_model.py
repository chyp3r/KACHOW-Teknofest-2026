from typing import Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class TrainingSampleModel(Base, TimestampMixin):
    """Türetilmiş bir tercih-çifti örneği; bir yöneticinin gördüğü veri
    (`GET /companies/{id}/training-samples`) ile bir eğitim çalıştırmasının
    fiilen okuduğu veri kanıtlanabilir şekilde aynı satırlar olsun diye
    kalıcı hale getirilir (Faz C3, #187).

    `source` bugün `"explicit_feedback"`tir -- derecelendirilen metni bir
    `drafts` satırına geri çözülebilen `feedback` oylarından derlenir (bkz.
    `app.ai.training.dataset.compile_pairs_from_feedback`). `"hitl_
    rejection"` / `"hitl_revision"` / `"gate_approval"` (planın işaret
    ettiği HITL onayla/reddet/revize et izinden gelen örtük sinyal) ayrılmış
    değerlerdir, henüz üretilmezler -- nedeni için #187'nin gövdesine
    bakın: `drafts.status` bugün bir kullanıcı kabul/red kararını değil,
    iş akışı sonucunu (`COMPLETED`/`FAILED`/`INTERRUPTED`) kaydeder, bu
    yüzden özel bir karar alanı olmadan ondan bir tercih etiketi türetmek
    veriyi sessizce yanlış etiketlerdi. Bu sütundaki `target_kind` şeklinde
    gevşeklik `FeedbackModel.target_kind`'ı yansıtır.

    `chosen`/`rejected`, şimdiye kadar uygulanan tek kaynak için yapı
    gereği tek kanatlıdır: bir geri bildirim oyu bir çiftin bir tarafıdır
    (bir 👍 yalnızca `chosen` olan bir satırdır, bir 👎 yalnızca
    `rejected`), asla ikisi birden değil -- tam mantık için
    `PreferencePair` üzerindeki sınıf docstring'ine bakın.
    """

    __tablename__ = "training_samples"
    __table_args__ = (
        UniqueConstraint("company_id", "pair_hash", name="uq_training_samples_company_pair_hash"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    #: Varsa, bu satırı en son hangi compile-and-mine çalıştırmasının
    #: ürettiği/yenilediği -- nullable olabilir çünkü derleme (`POST
    #: .../training-samples/compile`) bir yöneticinin fiilen eğitimden
    #: bağımsız olarak çalıştırabileceği bir adımdır.
    training_run_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("training_runs.id"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: Bunun türetildiği ham satıra geri gevşek referanslar --
    #: `FeedbackModel.draft_id` ile aynı gevşeklik, yalnızca izlenebilirlik
    #: için, FK yok.
    source_feedback_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    source_draft_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    prompt_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chosen: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejected: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    #: Yeniden derlemenin üzerine upsert yaptığı kimlik -- bunun nasıl
    #: türetildiği için `app.ai.training.dataset`'e bakın; derleyicinin
    #: tekrar çalıştırılmasını idempotent tutar.
    pair_hash: Mapped[str] = mapped_column(String, nullable=False)
    #: Bu örneği tüketmiş `training_runs.id`'lerin `list[str]`'i.
    used_in_runs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
