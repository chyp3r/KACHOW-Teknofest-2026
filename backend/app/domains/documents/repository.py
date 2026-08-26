from typing import List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.model.document_model import DocumentModel


class DocumentRepository:
    """`documents`'in arkasındaki sahiplik + listeleme kaydı (bkz. `DocumentModel`).

    Her metot açık bir `company_id` alır ve buna göre filtreler --
    çağıranın istediği herhangi bir sahiplik filtrelemesinin üzerine
    eklenen zorunlu kiracı sınırı (bkz. kiracılık planının Faz 1'i). Sahip
    kapsamlama parametrelerinin aksine, burada hiçbir yerde "company_id=None
    tüm şirketler demektir" kaçış kapısı yoktur: eksik bir şirket sınırı
    bir hatadır, desteklenen bir mod değil.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, document: DocumentModel) -> DocumentModel:
        """Yeni analiz edilmiş bir belgeyi kaydet."""
        self.db.add(document)
        await self.db.flush()
        return document

    async def get_by_id(self, storage_path: str, company_id: str) -> Optional[DocumentModel]:
        """`company_id` kapsamında, depolama yoluna göre bir belgenin kayıt satırını getir."""
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
        """`company_id` içinde `owner_id`'nin görebildiği belgeleri, en yeni önce listele.

        `owner_id=None` şirketteki her belgeyi listeler -- ADMIN/MANAGER/ROOT
        "şirket geneli" görünümü (bkz.
        `app.core.permissions.role_checker.bypasses_ownership`), asla
        şirketler arası bir görünüm değil: `company_id` her durumda her
        zaman uygulanır.
        """
        query = select(DocumentModel).where(DocumentModel.company_id == company_id)
        if owner_id is not None:
            query = query.where(DocumentModel.owner_id == owner_id)
        query = query.order_by(DocumentModel.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_for_owner(self, company_id: str, owner_id: Optional[str]) -> int:
        """Sayfalama için, `company_id` içinde `owner_id`'nin görebildiği toplam belge sayısı."""
        query = select(func.count()).select_from(DocumentModel).where(
            DocumentModel.company_id == company_id
        )
        if owner_id is not None:
            query = query.where(DocumentModel.owner_id == owner_id)
        result = await self.db.execute(query)
        return result.scalar_one()

    async def delete(self, storage_path: str, company_id: str) -> None:
        """`company_id` kapsamında, bir belgenin kayıt satırını kaldır.

        Taslakların aksine, belgeler kalıcı olarak silinir (hard-delete) --
        satırın hâlâ var olmasına bağlı bir versiyon zinciri veya audit okuma
        yolu yoktur, ve bunun geride bıraktığı ham dosya/analiz
        önbelleği/vektör parçaları çağıran tarafından temizlenir (bkz.
        `DocumentService.delete_document`).
        """
        await self.db.execute(
            delete(DocumentModel).where(
                DocumentModel.id == storage_path, DocumentModel.company_id == company_id
            )
        )
        await self.db.flush()

    async def is_owned_by(self, storage_path: str, owner_id: str, company_id: str) -> bool:
        """`storage_path`'in kayıtlı olup olmadığı, `company_id` içinde olup olmadığı ve `owner_id`'ye ait olup olmadığı.

        IDOR açığını gerçekten kapatan tek çağrı: bir belgenin içeriğinin
        her okunması -- sohbetin `document_id`'si veya
        `GET /documents/{storage_path}` endpoint'i üzerinden -- içerik
        döndürülmeden önce bundan geçmelidir.
        """
        document = await self.get_by_id(storage_path, company_id)
        return document is not None and document.owner_id == owner_id
