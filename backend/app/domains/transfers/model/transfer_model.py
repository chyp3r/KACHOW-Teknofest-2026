from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class ArtifactTransferModel(Base, TimestampMixin):
    """Herhangi bir kanaldan yapılan bir belge (taslak/evrak) transferi.

    Her transfer yolunun -- manuel sohbet gönderimi, eski `POST
    /drafts/{id}/send` REST uç noktası ve (Faz 4) AI destekli akış --
    `ArtifactTransferService.execute` üzerinden tam olarak tek bir satır
    yazdığı tek kayıt. Bu, bilinçli olarak sahtekarlığa karşı korumalı
    `audit_log` hash zincirinin (`app.domains.audit`) yerine geçmez --
    o, commit sonrasında ayrıca, best-effort olarak yazılır. Bu tablo
    sorgulanabilir alan (domain) kaydıdır: "kim, kime, hangi kanaldan,
    hangi sonuçla ne gönderdi" sorusu tek satırda, tek sorguyla yanıtlanır.

    `source_artifact_id`, `drafts.document_id`'nin zaten sahip olduğu aynı
    gevşeklikte bir referanstır (bir `drafts.id` ya da bir
    `documents.id`/storage_path) -- `artifact_kind`, hangi tabloya işaret
    ettiğini netleştirir. `snapshot_ref` alıcının kendi kopyasıdır: bir
    taslak için (transfer anında çatallanmış) yeni bir `drafts.id`, bir
    evrak için yeni bir `document_pool_items.id`.
    """

    __tablename__ = "artifact_transfers"
    __table_args__ = (
        #: `UniqueConstraint` değil, kısmi (partial) benzersiz indeks --
        #: `ConversationModel.dm_key`'in kendi indeksiyle aynı gerekçe:
        #: çoğu transfer hiç idempotency anahtarı vermez ve NULL-vs-NULL
        #: asla çakışmamalıdır.
        Index(
            "uq_artifact_transfers_idempotency",
            "company_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    #: "draft" | "document"
    artifact_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_artifact_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: `artifact_kind == "draft"` olduğunda transfer edilen taslak
    #: versiyonu -- transfer anında sabitlenir, böylece aynı taslağın
    #: sonraki bir revizyonu bu satırın gönderildiğini iddia ettiği şeyi
    #: asla sessizce değiştirmez.
    source_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    snapshot_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    recipient_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    conversation_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=True
    )
    message_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("conversation_messages.id"), nullable=True
    )
    #: "chat" | "ai" | "rest"
    channel: Mapped[str] = mapped_column(String, nullable=False)
    #: Yalnızca kullanıcının sonradan onayladığı bir Faz 4 AI önerisi
    #: alıcı için True -- bu fazın manuel kanalları tarafından asla
    #: ayarlanmaz.
    ai_suggested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: "routing_unit" | "favorite_rank" | "explicit_name" -- yalnızca Faz 4.
    recommendation_source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    recommendation_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    #: Alıcının birincil biriminin belgenin kendi `destination_unit_id`'sinden
    #: farklı olup olmadığı -- burada `TransferPolicy` tarafından bir kez
    #: hesaplanır, bunu kendi başına değerlendirmesi için asla bir çağırana
    #: (LLM dahil) bırakılmaz.
    cross_unit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Yalnızca gelecekteki otomatik/sistem başlatmalı bir transfer için
    #: False olabilir -- bu fazın desteklediği her kanal, kendisi zaten
    #: onay anlamına gelen, işlemi yapan kullanıcının kendi HTTP çağrısını
    #: gerektirir.
    confirmed_by_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: "permit" | "deny" -- bu transferin altında yürütüldüğü politika
    #: kararı. Bir satır yalnızca "permit" için var olur; bir "deny" asla
    #: kalıcı hale gelmez (bkz. `ArtifactTransferService.execute`),
    #: dolayısıyla bu kolon bugün her zaman "permit"tir, reddedilen bir
    #: girişimin yine de kaydedilmeye değer olabileceği Faz 4 denetim izi
    #: (audit trail) şekli için tutulmaktadır.
    policy_decision: Mapped[str] = mapped_column(String, nullable=False, default="permit")
    policy_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: "executed" | "failed" | "withdrawn"
    status: Mapped[str] = mapped_column(String, nullable=False, default="executed")
    #: Çağıranın sağladığı idempotency belirteci. Çoğu manuel gönderim için
    #: `None`; Faz 4 AI kanalı için gereklidir (`f"intent:{intent_id}"`),
    #: böylece tekrarlanan bir onay asla yeniden yürütülmez.
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
