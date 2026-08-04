from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.model.document_model import DocumentModel

#: Columns an upsert must never copy from the incoming transient instance.
_NOT_COPIED_ON_UPSERT = frozenset({"storage_path", "created_at", "updated_at"})


class DocumentRepository:
    """Data access for analysed incoming documents (evrak).

    Flushes but never commits: ``get_db`` owns the transaction and commits when the
    request completes, so committing here would move the transaction boundary into
    the repository layer and take rollback away from the caller.
    """

    def __init__(self, db: AsyncSession):
        """Initialise the repository.

        Args:
            db: Active asynchronous session.
        """
        self.db = db

    async def upsert(self, document: DocumentModel) -> DocumentModel:
        """Store an analysis, replacing any previous one for the same document.

        Upsert rather than insert because re-analysing an existing upload is a
        normal operation, and the storage path is the identity.

        Args:
            document: The record to store.

        Returns:
            The stored record.
        """
        existing = await self.get_by_storage_path(document.storage_path)
        if existing is None:
            self.db.add(document)
            await self.db.flush()
            return document

        for column in DocumentModel.__table__.columns.keys():
            # The key never changes, and the timestamps belong to TimestampMixin:
            # a transient instance carries None for both, so copying them across
            # would write NULL over created_at and defeat updated_at's onupdate.
            if column in _NOT_COPIED_ON_UPSERT:
                continue
            setattr(existing, column, getattr(document, column))
        await self.db.flush()
        return existing

    async def get_by_storage_path(self, storage_path: str) -> Optional[DocumentModel]:
        """Fetch one analysis by its storage path.

        Args:
            storage_path: The document's storage key.

        Returns:
            The record, or None when nothing is stored for that path.
        """
        result = await self.db.execute(
            select(DocumentModel).where(DocumentModel.storage_path == storage_path)
        )
        return result.scalar_one_or_none()

    async def get_page(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        document_type: Optional[str] = None,
        compliance_status: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[DocumentModel], int]:
        """Fetch a page of analyses, newest first, with the unpaginated total.

        Returns the total alongside the rows because the listing endpoint reports
        both, and counting in SQL avoids loading every row to measure the library.

        Args:
            offset: Number of records to skip.
            limit: Maximum number of records to return.
            document_type: Restrict to one document type.
            compliance_status: Restrict to one compliance status.
            user_id: Restrict to the documents of one user.

        Returns:
            The page of records and the total number matching the filters.
        """
        filters = []
        if document_type:
            filters.append(DocumentModel.document_type == document_type)
        if compliance_status:
            filters.append(DocumentModel.compliance_status == compliance_status)
        if user_id:
            filters.append(DocumentModel.user_id == user_id)

        total = await self.db.scalar(
            select(func.count()).select_from(DocumentModel).where(*filters)
        )
        result = await self.db.execute(
            select(DocumentModel)
            .where(*filters)
            .order_by(DocumentModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), int(total or 0)
