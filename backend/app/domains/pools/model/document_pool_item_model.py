from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class DocumentPoolItemModel(Base, TimestampMixin):
    """One document filed into one pool (see `DocumentPoolModel`).

    A document may sit in more than one pool (a manager's push into an
    employee's personal pool doesn't remove it from wherever it already
    was), so this is a join row, not a `pool_id` column on `documents`
    itself -- `UNIQUE(pool_id, document_id)` only prevents the same
    document appearing twice in the *same* pool.
    """

    __tablename__ = "document_pool_items"
    __table_args__ = (
        UniqueConstraint("pool_id", "document_id", name="uq_document_pool_items_pool_document"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    pool_id: Mapped[str] = mapped_column(
        String, ForeignKey("document_pools.id"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(
        String, ForeignKey("documents.id"), nullable=False, index=True
    )
    added_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    #: "upload" (the owner's own document, filed automatically) | "manager_push"
    #: (`POST /pools/push`) | "share" (reserved for Faz 5's draft/document
    #: sharing, unused today).
    source: Mapped[str] = mapped_column(String, nullable=False, default="upload")
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: Set when the pool's owner acknowledges/reads a pushed item (`POST
    #: /pools/items/{id}/acknowledge`). `NULL` forever for a plain "upload"
    #: item -- acknowledgement only means something for something *pushed*
    #: to you.
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
