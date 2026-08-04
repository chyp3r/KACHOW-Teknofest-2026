from typing import Any, Optional

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums.document_status import DocumentStatus
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin

# Imported for its side effect: the user_id foreign key below resolves "users.id"
# against the shared MetaData, so the users table has to be registered in it.
# Without this, importing this module on its own raises NoReferencedTableError the
# first time the mapper is configured -- and only then, which makes it an awkward
# failure to trace back to a missing import.
from app.domains.users.model.user_model import UserModel  # noqa: F401


class DocumentModel(Base, TimestampMixin):
    """An analysed incoming document (evrak), persisted for later retrieval.

    Replaces the pair of local JSON files this used to be written to
    (``uploads_metadata.json`` plus a per-document ``_analysis.json``). Those were
    a working stopgap but had no story for concurrent writers beyond a process-local
    lock, no query surface, and no survival across containers with an ephemeral
    volume.

    Keyed on ``storage_path`` rather than a surrogate id, because that is already
    the analysis identity everywhere else: ``DocumentAnalysisResponseSchema`` sets
    ``analysis_id = storage_path`` and ``GET /documents/{storage_path}`` addresses
    documents by it. Introducing a second identifier would mean maintaining a
    mapping for no gain.

    ``fields`` / ``missing_fields`` / ``mevzuat_references`` are ``JSON`` columns
    rather than child tables: they are read back as whole documents and never
    queried field-by-field, so normalising them would buy joins nobody makes while
    forcing every ``EvrakField`` change into a migration.
    """

    __tablename__ = "documents"

    storage_path: Mapped[str] = mapped_column(String(512), primary_key=True)
    # Nullable: /analyze is reachable without a token when auth is disabled, and an
    # unattributed analysis is still worth keeping.
    user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )

    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Extraction provenance. `used_ocr` in particular must reach whoever reads the
    # record: OCR-derived fields carry letter errors and need verifying.
    extractor: Mapped[str] = mapped_column(String(64), nullable=False)
    used_ocr: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    document_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    document_type_label: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)

    fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    missing_fields: Mapped[list[Any]] = mapped_column(
        JSON, default=list, nullable=False
    )
    mevzuat_references: Mapped[list[Any]] = mapped_column(
        JSON, default=list, nullable=False
    )
    scrubbed_markers: Mapped[list[Any]] = mapped_column(
        JSON, default=list, nullable=False
    )
    compliance_status: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )

    #: Extracted text, kept so document Q&A and re-analysis do not have to fetch
    #: and re-parse the original file.
    extracted_text: Mapped[str] = mapped_column(Text, default="", nullable=False)

    status: Mapped[str] = mapped_column(
        String(32), default=DocumentStatus.COMPLETED.value, nullable=False
    )
