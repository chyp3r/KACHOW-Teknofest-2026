from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class ConversationParticipantModel(Base, TimestampMixin):
    """Bir kullanıcının bir konuşmadaki üyeliği -- bu satır erişim
    izninin KENDİSİDİR.

    `role_in_conversation`; `"owner"` (grubun kurucusu veya sonradan
    terfi ettirilen biri -- her iki tarafın eşit olduğu bir DM için
    anlamsız) veya `"member"`, `units.role_in_unit` gibi açık string'dir.

    `left_at` yumuşak-ayrılmadır: eski bir katılımcı konuşmadayken zaten
    var olan geçmişe okuma erişimini korur (satırı hâlâ orada, sadece
    ayrılmış olarak işaretli), ama yeni mesaj gönderemez ve
    `list_for_conversation`'ın "kimler aktif" görünümünde görünmeyi
    bırakır. Bu satırın hard delete'i yoktur -- bir gruptan ayrıldıktan
    sonra yeniden katılmak, aksi takdirde ya kafa karıştırıcı bir
    geçmişle eski bir satırı diriltir ya da
    `uq_conversation_participants_conv_user` ile çakışır.

    `last_read_message_id` gevşek bir işaretçidir (FK yok -- bir mesaj
    altından soft-delete edilebilir), yalnızca işaret ettiği mesajın
    `created_at`'ine karşı zaman damgalarını karşılaştırarak okunmamış
    sayısını hesaplamak için kullanılır (mesaj id'leri sıralı değil,
    opak uuid-hex'tir, bu yüzden "şu tarihten beri okunmamış" id'leri
    doğrudan karşılaştıramaz). `created_at` (`TimestampMixin`'den) zaten
    "katıldığı tarih" görevini de görür -- bunun için ayrı bir kolon
    yoktur.
    """

    __tablename__ = "conversation_participants"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "user_id", name="uq_conversation_participants_conv_user"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    role_in_conversation: Mapped[str] = mapped_column(String, nullable=False, default="member")
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_read_message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    muted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
