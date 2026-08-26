from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class ConversationModel(Base, TimestampMixin):
    """Şirket kullanıcıları arasında bir DM veya grup thread'i.

    `kind`; `"dm"` veya `"group"`, açık string (`units.role_in_unit` ile
    aynı esneklik). `dm_key`, `kind="dm"` bir satır için sıralanmış
    `"user_a_id:user_b_id"` çiftidir, bir grup için `None` -- `(company_id,
    dm_key) WHERE kind = 'dm'` üzerindeki kısmi unique index (bkz.
    `0022_messaging` migration'ı) aynı iki kullanıcı arasında ikinci bir
    DM'i yapısal olarak imkansız kılar, böylece
    `ConversationService.open_dm` diğer taraftan gelen eşzamanlı bir
    açmaya karşı hiçbir zaman bir çift-kontrol yarışına girmek zorunda
    kalmaz.

    Bir konuşmaya erişim bir ABAC kararı değildir -- çağıran için bir
    `ConversationParticipantModel` satırının var olup olmadığıyla
    cevaplanır, `draft_shares`'in zaten kullandığı aynı "satırın kendisi
    izindir" örüntüsü (bkz.
    `app.domains.drafts.draft_share_service.DraftShareService`'in kendi
    docstring'i).
    """

    __tablename__ = "conversations"
    __table_args__ = (
        #: `UniqueConstraint` değil kısmi unique index -- aynı gerekçe
        #: `uq_unit_memberships_one_primary_per_user`'da olduğu gibi:
        #: Postgres'te bildirimsel bir "false olduğunda hariç unique"
        #: biçimi yoktur, bu yüzden bunun yerine `WHERE kind = 'dm'` ile
        #: kapsamlandırılmış düz bir index kullanılır.
        Index(
            "uq_conversations_dm_key",
            "company_id",
            "dm_key",
            unique=True,
            postgresql_where=text("kind = 'dm'"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    #: Grup görünen adı. Bir DM için `None` -- bir DM'in "title"ı her
    #: zaman diğer katılımcısından türetilir, servis/frontend tarafından
    #: hesaplanır, hiçbir zaman saklanmaz (bir kullanıcı adı değiştiğinde
    #: senkronize tutulacak hiçbir şey yoktur).
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    dm_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    #: En son `conversation_messages` satırından denormalize edilmiştir,
    #: aynı flush içinde `ConversationMessageRepository.create` tarafından
    #: senkronize tutulur -- konuşma listesi satır başına aggregate join
    #: olmadan buna göre sıralanır.
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
