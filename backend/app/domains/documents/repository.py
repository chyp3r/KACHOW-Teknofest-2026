from typing import List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.model.document_model import DocumentModel


class DocumentRepository:
    """The ownership + listing registry backing `documents` (see `DocumentModel`).

    Every method takes an explicit `company_id` and filters on it -- the
    mandatory tenant boundary (see the tenancy plan's Faz 1) -- on top of
    whatever ownership filtering the caller also asks for. There is no
    "company_id=None means every company" escape hatch anywhere here, unlike
    the owner-scoping parameters: a missing company boundary is a bug, not a
    supported mode.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, document: DocumentModel) -> DocumentModel:
        """Register a newly analysed document."""
        self.db.add(document)
        await self.db.flush()
        return document

    async def get_by_id(self, storage_path: str, company_id: str) -> Optional[DocumentModel]:
        """Fetch a document's registry row by storage path, scoped to `company_id`."""
        result = await self.db.execute(
            select(DocumentModel).where(
                DocumentModel.id == storage_path, DocumentModel.company_id == company_id
            )
        )
        return result.scalar_one_or_none()

    async def list_for_owner(
        self,
        company_id: str,
        owner_id: Optional[str],
        skip: int = 0,
        limit: int = 100,
    ) -> List[DocumentModel]:
        """List documents visible to `owner_id` within `company_id`, newest first.

        `owner_id=None` lists every document in the company -- the
        ADMIN/MANAGER/ROOT "company-wide" view (see
        `app.core.permissions.role_checker.bypasses_ownership`), never a
        cross-company one: `company_id` is always applied regardless.
        """
        query = select(DocumentModel).where(DocumentModel.company_id == company_id)
        if owner_id is not None:
            query = query.where(DocumentModel.owner_id == owner_id)
        query = query.order_by(DocumentModel.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_for_owner(self, company_id: str, owner_id: Optional[str]) -> int:
        """Total documents visible to `owner_id` within `company_id`, for pagination."""
        query = select(func.count()).select_from(DocumentModel).where(
            DocumentModel.company_id == company_id
        )
        if owner_id is not None:
            query = query.where(DocumentModel.owner_id == owner_id)
        result = await self.db.execute(query)
        return result.scalar_one()

    async def delete(self, storage_path: str, company_id: str) -> None:
        """Remove a document's registry row, scoped to `company_id`.

        Unlike drafts, documents are hard-deleted -- there is no version
        chain or audit read path that depends on the row still existing,
        and the raw file/analysis cache/vector chunks this leaves behind
        are cleaned up by the caller (see `DocumentService.delete_document`).
        """
        await self.db.execute(
            delete(DocumentModel).where(
                DocumentModel.id == storage_path, DocumentModel.company_id == company_id
            )
        )
        await self.db.flush()

    async def is_owned_by(self, storage_path: str, owner_id: str, company_id: str) -> bool:
        """Whether `storage_path` is registered, in `company_id`, and belongs to `owner_id`.

        The one call that actually closes the IDOR gap: every read of a
        document's content -- through chat's `document_id` or the
        `GET /documents/{storage_path}` endpoint -- must pass this before
        the content is returned.
        """
        document = await self.get_by_id(storage_path, company_id)
        return document is not None and document.owner_id == owner_id
