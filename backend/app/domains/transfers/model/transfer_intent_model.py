from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class ArtifactTransferIntentModel(Base, TimestampMixin):
    """Önerilen bir transfer için AI kanalının onay yaşam döngüsü.

    **Henüz hiçbir yerde okunmuyor veya yazılmıyor.** RLS politikası ve
    tablo şekli `artifact_transfers` ile birlikte teslim edilsin diye şimdi
    (Faz 3, #199) migrate edildi, ancak bunu sahiplenen durum makinesi --
    `TransferIntentService`, CAS tabanlı `state` geçişleri,
    `transfer_gate_node`'un `interrupt()`'ı -- Faz 4'tür. Burada var olması
    ama kullanılmaması bilinçli olarak güvenlidir: RLS zaten uygulanıyor
    ve daha sonra okuyucu/yazıcı kodu eklemek dışında migrate edilecek
    bir şey yok.

    `state`, planın §I'sinde belgelenen yaşam döngüsünü taşıyacak:
    INTENT_DETECTED -> {AMBIGUOUS, RECIPIENT_RESOLVED, UNRESOLVED} ->
    POLICY_CHECKED -> {AWAITING_CONFIRMATION, POLICY_DENIED} ->
    {CONFIRMED, CANCELLED} -> {TRANSFER_EXECUTED, FAILED}. Tek bir koşullu
    `UPDATE ... WHERE state = :expected` (satır seviyeli CAS) ile ilerler,
    böylece tekrarlanan veya eskimiş bir onay bir yarış durumuna değil
    "0 satır değişti" sonucuna varır.
    """

    __tablename__ = "artifact_transfer_intents"
    __table_args__ = (
        #: `thread_id` üzerinde düz tek kolonlu bir indeks değil, bileşik
        #: bir indeks -- buradaki her gerçek sorgu "bu thread'in aktif
        #: intent'(ler)i" biçimindedir, yani `(thread_id, state)`; Postgres
        #: yine de aynı indeksin öndeki kolonu üzerinden sadece thread_id'ye
        #: göre bir aramaya hizmet edebilir.
        Index("ix_artifact_transfer_intents_thread_state", "thread_id", "state"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    #: Bu intent'in ait olduğu LangGraph thread'i -- `ChatService._thread_id`'nin
    #: ürettiği aynı bileşik id.
    thread_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    requested_by: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    artifact_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_artifact_id: Mapped[str] = mapped_column(String, nullable=False)
    source_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolved_recipient_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    #: İsim çözümlemesi belirsiz olduğunda (aynı isimde birden fazla
    #: kullanıcı) aday listesi -- belirsizlik giderme interrupt'ında
    #: olduğu gibi gösterilir, model tarafından asla yeniden tahmin
    #: edilmez.
    candidate_recipients: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False)
    policy_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    #: `policy_snapshot`'un sha256'sı, onay anında yeniden hesaplanır ve
    #: karşılaştırılır -- "politika kontrol edildi" ile "kullanıcı onaya
    #: tıkladı" arasındaki TOCTOU koruması.
    policy_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    cross_unit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resulting_transfer_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("artifact_transfers.id"), nullable=True
    )
