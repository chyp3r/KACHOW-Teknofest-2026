from typing import Optional

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums.sensitivity_level import SensitivityLevel
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class DocumentModel(Base, TimestampMixin):
    """The ownership + listing registry for uploaded documents.

    The document's own text and full analysis stay in the local JSON cache
    written by `app.domains.documents.service.DocumentService` (a separate
    concern -- migrating that blob storage off the filesystem is its own,
    larger piece of work, out of scope here). This table exists to answer
    exactly one question cheaply and correctly: "does `storage_path` belong
    to `owner_id`?" -- the check that was missing entirely before (see the
    architecture migration's B8 finding: any caller who knew or guessed a
    storage_path could read another user's document through chat).

    `owner_id` is nullable because `settings.REQUIRE_AUTH=False` (the default
    demo/dev mode) uploads documents with no authenticated user at all --
    those rows stay ownerless and visible to everyone, preserving today's
    demo behaviour. Ownership is only enforced once a real user is attached.
    """

    __tablename__ = "documents"

    #: The storage backend's key (see `DocumentService._store`), reused as
    #: the primary key rather than a separate surrogate id -- every other
    #: layer (the local analysis cache, Qdrant's `storage_path` payload
    #: filter, the API's `{storage_path}` path parameter) already addresses
    #: a document by this value.
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    owner_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    document_type: Mapped[str] = mapped_column(String, nullable=False, default="")
    document_type_label: Mapped[str] = mapped_column(String, nullable=False, default="")
    compliance_status: Mapped[str] = mapped_column(String, nullable=False, default="")
    summary: Mapped[str] = mapped_column(String, nullable=False, default="")
    #: The document's assessed confidentiality grade (``app.ai.guardrails.
    #: sensitivity.assess``), stored as the ``SensitivityLevel`` string so
    #: listing/retrieval can filter without re-reading the analysis cache.
    #: Defaults to ``UNMARKED``, not ``TASNIF_DISI`` -- the same "an absent
    #: grade is not the same fact as a stated one" reasoning `EvrakField.
    #: gizlilik_derecesi` already documents.
    sensitivity_level: Mapped[str] = mapped_column(
        String, nullable=False, default=SensitivityLevel.UNMARKED.value
    )
    #: True when the document scan found at least one PII pattern match
    #: (TCKN, IBAN, phone, address) regardless of confidentiality grade.
    pii_flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
