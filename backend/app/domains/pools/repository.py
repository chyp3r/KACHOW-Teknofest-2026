from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.model.document_model import DocumentModel
from app.domains.pools.model.document_pool_item_model import DocumentPoolItemModel
from app.domains.pools.model.document_pool_model import DocumentPoolModel


class DocumentPoolRepository:
    """Repository for `document_pools` (see `DocumentPoolModel`).

    Every method takes an explicit `company_id`, same convention as every
    other repository since the tenancy work.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, pool_id: str, company_id: str) -> Optional[DocumentPoolModel]:
        result = await self.db.execute(
            select(DocumentPoolModel).where(
                DocumentPoolModel.id == pool_id, DocumentPoolModel.company_id == company_id
            )
        )
        return result.scalar_one_or_none()

    async def get_default_for_owner(
        self, owner_type: str, owner_id: str, company_id: str
    ) -> Optional[DocumentPoolModel]:
        result = await self.db.execute(
            select(DocumentPoolModel).where(
                DocumentPoolModel.owner_type == owner_type,
                DocumentPoolModel.owner_id == owner_id,
                DocumentPoolModel.company_id == company_id,
                DocumentPoolModel.is_default.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def create(self, pool: DocumentPoolModel) -> DocumentPoolModel:
        self.db.add(pool)
        await self.db.flush()
        return pool

    async def get_or_create_default(
        self, owner_type: str, owner_id: str, company_id: str, name: str
    ) -> DocumentPoolModel:
        """Fetch `owner`'s default pool, lazily creating it on first use.

        Called both from `DocumentService` (every upload files itself into
        the uploader's own default pool) and from the push flow (a
        recipient's default pool is where a manager-pushed document lands).
        """
        existing = await self.get_default_for_owner(owner_type, owner_id, company_id)
        if existing is not None:
            return existing
        return await self.create(
            DocumentPoolModel(
                id=uuid4().hex,
                company_id=company_id,
                owner_type=owner_type,
                owner_id=owner_id,
                name=name,
                is_default=True,
            )
        )


class DocumentPoolItemRepository:
    """Repository for `document_pool_items` (see `DocumentPoolItemModel`)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, item_id: str, company_id: str) -> Optional[DocumentPoolItemModel]:
        result = await self.db.execute(
            select(DocumentPoolItemModel).where(
                DocumentPoolItemModel.id == item_id, DocumentPoolItemModel.company_id == company_id
            )
        )
        return result.scalar_one_or_none()

    async def exists(self, pool_id: str, document_id: str) -> bool:
        result = await self.db.execute(
            select(DocumentPoolItemModel.id).where(
                DocumentPoolItemModel.pool_id == pool_id,
                DocumentPoolItemModel.document_id == document_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_by_pool_and_document(
        self, pool_id: str, document_id: str
    ) -> Optional[DocumentPoolItemModel]:
        """The one row `UNIQUE(pool_id, document_id)` guarantees is unique,
        when it exists -- used by `PoolService.file_transferred_document`
        to refresh an already-transferred item in place instead of hitting
        that constraint on a re-send."""
        result = await self.db.execute(
            select(DocumentPoolItemModel).where(
                DocumentPoolItemModel.pool_id == pool_id,
                DocumentPoolItemModel.document_id == document_id,
            )
        )
        return result.scalar_one_or_none()

    async def save(self, item: DocumentPoolItemModel) -> DocumentPoolItemModel:
        """Flush pending attribute mutations on an already-attached item."""
        await self.db.flush()
        return item

    async def list_for_pool(
        self, pool_id: str, company_id: str, skip: int = 0, limit: int = 100
    ) -> List[Tuple[DocumentPoolItemModel, DocumentModel]]:
        """Every item in `pool_id`, newest first, joined with its document's file name."""
        result = await self.db.execute(
            select(DocumentPoolItemModel, DocumentModel)
            .join(DocumentModel, DocumentModel.id == DocumentPoolItemModel.document_id)
            .where(
                DocumentPoolItemModel.pool_id == pool_id,
                DocumentPoolItemModel.company_id == company_id,
            )
            .order_by(DocumentPoolItemModel.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return [(item, document) for item, document in result.all()]

    async def count_for_pool(self, pool_id: str, company_id: str) -> int:
        result = await self.db.execute(
            select(func.count(DocumentPoolItemModel.id)).where(
                DocumentPoolItemModel.pool_id == pool_id,
                DocumentPoolItemModel.company_id == company_id,
            )
        )
        return result.scalar_one()

    async def create(self, item: DocumentPoolItemModel) -> DocumentPoolItemModel:
        self.db.add(item)
        await self.db.flush()
        return item

    async def delete(self, item_id: str, company_id: str) -> bool:
        result = await self.db.execute(
            delete(DocumentPoolItemModel).where(
                DocumentPoolItemModel.id == item_id, DocumentPoolItemModel.company_id == company_id
            )
        )
        await self.db.flush()
        return result.rowcount > 0

    async def acknowledge(self, item_id: str, company_id: str) -> Optional[DocumentPoolItemModel]:
        item = await self.get_by_id(item_id, company_id)
        if item is None:
            return None
        item.acknowledged_at = datetime.now(timezone.utc)
        await self.db.flush()
        return item
