from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
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
    #: "upload" (the owner's own document, filed automatically) |
    #: "manager_push" (`POST /pools/push`) | "transfer"
    #: (`app.domains.transfers.ArtifactTransferService` -- what the
    #: previously-reserved `"share"` value was for; renamed to match the
    #: domain that actually implements it, see `metadata_snapshot` below) |
    #: "adopted" (`POST /pools/items/{id}/adopt`, Faz 5, #205 -- a
    #: `"transfer"` item the pool's own owner turned into a fully-owned
    #: copy; `document_id` now points at their own `documents` row instead
    #: of the sender's).
    source: Mapped[str] = mapped_column(String, nullable=False, default="upload")
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: Set when the pool's owner acknowledges/reads a pushed item (`POST
    #: /pools/items/{id}/acknowledge`). `NULL` forever for a plain "upload"
    #: item -- acknowledgement only means something for something *pushed*
    #: to you.
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The sender for `source="transfer"` -- distinct from `added_by`,
    #: which for a transfer is whichever process actually inserted the row
    #: (the acting user on the chat/rest channels today; a future
    #: system-initiated path could differ). `NULL` for "upload"/
    #: "manager_push". Survives `adopt` (see `source` above) as provenance
    #: -- who originally sent it stays true even after the recipient turns
    #: the snapshot into their own owned copy.
    transferred_by: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    #: `documents`' mutable metadata (document_type, document_type_label,
    #: compliance_status, summary, sensitivity_level, pii_flagged), frozen
    #: at transfer time. The blob itself is never mutated by anything in
    #: this system, so sharing it is safe; this row's own metadata is what
    #: could otherwise drift out from under the recipient if the sender
    #: later edits the source document -- see the plan's §D5 for why a
    #: full copy was rejected in favor of this snapshot. `NULL` for every
    #: source other than "transfer" -- cleared back to `NULL` by `adopt`
    #: too, since an adopted item's `documents` row is now live and owned,
    #: not a frozen snapshot of someone else's.
    metadata_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
