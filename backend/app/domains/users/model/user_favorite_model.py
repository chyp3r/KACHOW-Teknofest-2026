from typing import Optional

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class UserFavoriteModel(Base, TimestampMixin):
    """Bir kullanıcının bir diğerini favori olarak işaretlemesi -- simetrik değildir.

    `owner_user_id`'nin `favorite_user_id`'yi favorilemesi tersini
    gerektirmez; her yön kendi satırıdır (veya yoktur). Bu, AI destekli
    belge/evrak transfer akışının (Faz 4) kullanıcının açıkça favori olarak
    adlandırmadığı birine herhangi bir şey göndermeden önce gerektirdiği
    geçittir -- bu gerekliliğin neden sadece AI kanalına özel olduğu, manuel
    sohbet/REST gönderimlerine değil, için planın politika bölümüne bakınız.
    """

    __tablename__ = "user_favorites"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id", "favorite_user_id", name="uq_user_favorites_owner_favorite"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    owner_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    favorite_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
