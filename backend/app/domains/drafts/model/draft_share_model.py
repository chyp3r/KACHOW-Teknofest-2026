from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class DraftShareModel(Base, TimestampMixin):
    """Bir kullanıcıdan diğerine gönderilmiş bir taslak versiyonu (şartnamedeki
    "çalışanlar arası taslak gönder/al" -- çalışandan çalışana taslak
    teslimatı).

    Bir oturumu değil, belirli bir ``drafts`` satırını (belirli bir
    versiyonu) hedefler -- ``DraftModel`` zaten yalnızca-ekleme (append-only)
    bir versiyon zinciridir, ve "geçerli taslağı" göndermek yalnızca
    gönderim anında en son satırının id'sini göndermek anlamına gelir;
    burada "daha sonra daha yeni bir versiyon gönderildi mi" diye takip
    edilecek bir şey yoktur, bu basitçe ikinci, ayrı bir paylaşım
    satırıdır.

    Ayrı bir inbox/outbox tablosu yoktur: "inbox" ``recipient_id = ben``,
    "outbox" ``sender_id = ben``dir, ikisi de bu tek tabloya karşı (bkz.
    ``DraftShareRepository.list_inbox``/``list_outbox``).
    """

    __tablename__ = "draft_shares"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    draft_id: Mapped[str] = mapped_column(String, ForeignKey("drafts.id"), nullable=False, index=True)
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    recipient_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    #: ``drafts.destination``'ın (üretim anındaki AI'ın routing önerisi)
    #: çözümlendiği birim; gönderim anında kopyalanır -- bkz.
    #: ``DraftShareService.send``. ``destination`` mevcut hiçbir birim
    #: adıyla eşleşmiyorsa (o zamandan beri yeniden adlandırılmış/silinmiş,
    #: ya da hiç routing kararı olmayan doğrudan bir taslak) `NULL`;
    #: hata değil, dürüst bir eşleşmeme.
    suggested_unit_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("units.id"), nullable=True
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: "sent" | "read" | "accepted" | "rejected" | "withdrawn" (durum değerleri).
    status: Mapped[str] = mapped_column(String, nullable=False, default="sent")
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    response_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
