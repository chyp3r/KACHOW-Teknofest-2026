from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.model.document_model import DocumentModel
from app.domains.pools.model.document_pool_item_model import DocumentPoolItemModel
from app.domains.pools.model.document_pool_model import DocumentPoolModel


class DocumentPoolRepository:
    """`document_pools` için repository (bkz. `DocumentPoolModel`).

    Her metot açık bir `company_id` alır, tenancy çalışmasından bu yana
    diğer tüm repository'lerle aynı kural.
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
        """`owner`'ın varsayılan havuzunu getirir, ilk kullanımda tembel
        (lazy) olarak oluşturur.

        Hem `DocumentService`'ten (her yükleme kendisini yükleyenin kendi
        varsayılan havuzuna dosyalar) hem de push akışından (bir manager
        tarafından push edilen belgenin ineceği yer, alıcının varsayılan
        havuzudur) çağrılır.
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
    """`document_pool_items` için repository (bkz. `DocumentPoolItemModel`)."""

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
        """Var olduğunda `UNIQUE(pool_id, document_id)`'nin benzersiz
        olmasını garantilediği tek satır -- `PoolService.
        file_transferred_document` tarafından, yeniden gönderimde o
        kısıtlamaya çarpmak yerine zaten transfer edilmiş bir öğeyi
        yerinde tazelemek için kullanılır."""
        result = await self.db.execute(
            select(DocumentPoolItemModel).where(
                DocumentPoolItemModel.pool_id == pool_id,
                DocumentPoolItemModel.document_id == document_id,
            )
        )
        return result.scalar_one_or_none()

    async def save(self, item: DocumentPoolItemModel) -> DocumentPoolItemModel:
        """Zaten bağlı bir öğe üzerindeki bekleyen attribute mutasyonlarını
        flush eder."""
        await self.db.flush()
        return item

    async def list_for_pool(
        self, pool_id: str, company_id: str, skip: int = 0, limit: int = 100
    ) -> List[Tuple[DocumentPoolItemModel, DocumentModel]]:
        """`pool_id` içindeki her öğe, en yeni önce, belgesinin dosya
        adıyla join edilmiş."""
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
