from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.model.document_model import DocumentModel


class DocumentRepository:
    """The ownership + listing registry backing `documents` (see `DocumentModel`)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, document: DocumentModel) -> DocumentModel:
        """Register a newly analysed document."""
        self.db.add(document)
        await self.db.flush()
        return document

    async def get_by_id(self, storage_path: str) -> Optional[DocumentModel]:
        """Fetch a document's registry row by its storage path."""
        result = await self.db.execute(
            select(DocumentModel).where(DocumentModel.id == storage_path)
        )
        return result.scalar_one_or_none()

    async def list_for_owner(
        self, owner_id: Optional[str], skip: int = 0, limit: int = 100
    ) -> List[DocumentModel]:
        """List documents visible to `owner_id`, newest first.

        `owner_id=None` (the `REQUIRE_AUTH=False` demo/dev path) lists every
        document regardless of owner -- unauthenticated mode has no concept
        of "someone else's document" to hide, matching the behaviour of the
        `uploads_metadata.json` listing this replaces.
        """
        query = select(DocumentModel)
        if owner_id is not None:
            query = query.where(DocumentModel.owner_id == owner_id)
        query = query.order_by(DocumentModel.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_for_owner(self, owner_id: Optional[str]) -> int:
        """Total documents visible to `owner_id`, for pagination."""
        documents = await self.list_for_owner(owner_id, skip=0, limit=10_000)
        return len(documents)

    async def delete(self, storage_path: str) -> None:
        """Remove a document's registry row.

        Unlike drafts, documents are hard-deleted -- there is no version
        chain or audit read path that depends on the row still existing,
        and the raw file/analysis cache/vector chunks this leaves behind
        are cleaned up by the caller (see `DocumentService.delete_document`).
        """
        await self.db.execute(delete(DocumentModel).where(DocumentModel.id == storage_path))
        await self.db.flush()

    async def is_owned_by(self, storage_path: str, owner_id: str) -> bool:
        """Whether `storage_path` is registered and belongs to `owner_id`.

        The one call that actually closes the IDOR gap: every read of a
        document's content -- through chat's `document_id` or the
        `GET /documents/{storage_path}` endpoint -- must pass this before
        the content is returned, once a real user is attached to the
        request.
        """
        document = await self.get_by_id(storage_path)
        return document is not None and document.owner_id == owner_id
