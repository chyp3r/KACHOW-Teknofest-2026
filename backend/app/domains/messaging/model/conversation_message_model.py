from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class ConversationMessageModel(Base, TimestampMixin):
    """Bir konuşmadaki tek bir mesaj -- text, artifact veya system.

    `kind`'a göre bölünmemiş tek bir tablo -- thread sıralaması tek bir
    tablodan gelmelidir (bölmek her thread okumasını zaman üzerinden bir
    UNION'a çevirirdi). `kind`; `"text"` (düz insan mesajı), `"artifact"`
    (bir taslak/evrak transfer bildirimi -- bkz. `artifact_transfer_id`;
    Faz 3'te tam olarak tanıtıldı) veya `"system"` ("X gruba eklendi"
    gibi üyelik olayları) olabilir.

    `artifact_transfer_id` -> `artifact_transfers.id` (o tablo var
    olduğunda `0024` migration'ı tarafından eklendi -- bu kolonun
    kendisi ondan öncedir, `0022` tarafından FK'sız oluşturuldu). Bir
    artifact mesajının kart içeriği (başlık, sürüm, gönderen, durum)
    asla `body`'ye cache'lenmez -- frontend bunu transfer satırından
    canlı okur, böylece geri çekilmiş/başarısız bir transferin kartı
    eski bir anlık görüntü yerine gerçeği yansıtır.

    `sender_id` yalnızca gelecekteki system-yazarlı bir satır için
    (`kind="system"`) nullable'dır; her `"text"`/`"artifact"` mesajının
    gerçek bir göndereni vardır.
    """

    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conversation_messages_conv_created", "conversation_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False, index=True
    )
    sender_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="text")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    artifact_transfer_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("artifact_transfers.id", name="fk_conversation_messages_artifact_transfer_id"),
        nullable=True,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
