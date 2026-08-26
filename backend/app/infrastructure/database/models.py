from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class TimestampMixin:
    """Miras alan herhangi bir tablo modeline otomatik olarak zaman dilimi
    farkında created_at ve updated_at zaman damgası alanları ekleyen ORM Mixin'i.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
