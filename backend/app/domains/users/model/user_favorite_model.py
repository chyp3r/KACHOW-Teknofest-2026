from typing import Optional

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class UserFavoriteModel(Base, TimestampMixin):
    """One user marking another as a favorite -- not symmetric.

    `owner_user_id` favoriting `favorite_user_id` does not imply the
    reverse; each direction is its own row (or absent). This is the gate
    the AI-assisted artifact transfer flow (Faz 4) requires before it may
    send anything to someone the user hasn't explicitly named a favorite --
    see the plan's policy section for why that requirement is scoped to the
    AI channel only, not manual chat/REST sends.
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
