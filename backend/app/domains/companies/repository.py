from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.companies.model.company_model import CompanyModel


class CompanyRepository:
    """Şirketlerle ilgili SQLAlchemy veritabanı işlemleri için repository.

    Sistemdeki diğer tüm repository'lerin aksine, bu repository bilinçli
    olarak şirkete özel (company-scoped) DEĞİLDİR -- bir şirket zaten
    kapsamlama biriminin kendisi olduğundan, şirketleri listelemek ve
    aramak doğası gereği yalnızca root'a özel, kiracılar arası bir
    işlemdir. Çağıranlar erişimi ``require_roles(UserRole.ROOT)`` ile
    (veya ileride ABAC'ın ``system:*`` eylemiyle) sınırlamalıdır; bu
    repository'nin herhangi bir filtreleme yapmasına güvenilmemelidir.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, company_id: str) -> Optional[CompanyModel]:
        """Birincil anahtar ID ile bir şirketi getirir; soft-delete edilmiş satırlar dahil."""
        result = await self.db.execute(select(CompanyModel).where(CompanyModel.id == company_id))
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Optional[CompanyModel]:
        """Benzersiz slug'ına göre bir şirketi getirir."""
        result = await self.db.execute(select(CompanyModel).where(CompanyModel.slug == slug))
        return result.scalar_one_or_none()

    async def list_all(self, *, offset: int = 0, limit: int = 20) -> List[CompanyModel]:
        """Silinmemiş şirketleri, sayfalanmış ve isme göre sıralı şekilde getirir."""
        result = await self.db.execute(
            select(CompanyModel)
            .where(CompanyModel.is_deleted == False)  # noqa: E712
            .order_by(CompanyModel.name)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_all(self) -> int:
        """Silinmemiş şirketleri sayar."""
        result = await self.db.execute(
            select(func.count()).select_from(CompanyModel).where(CompanyModel.is_deleted == False)  # noqa: E712
        )
        return result.scalar_one()

    async def create(self, company: CompanyModel) -> CompanyModel:
        """Yeni bir şirket kaydını veritabanına kalıcı olarak yazar."""
        self.db.add(company)
        await self.db.flush()
        return company

    async def update(self, company: CompanyModel, update_data: dict) -> CompanyModel:
        """Bir şirket modelinin niteliklerini günceller ve flush yapar."""
        for field, value in update_data.items():
            if hasattr(company, field) and value is not None:
                setattr(company, field, value)
        await self.db.flush()
        return company

    async def soft_delete(self, company: CompanyModel) -> CompanyModel:
        """Satırı kaldırmadan bir şirketi silinmiş ve pasif olarak işaretler.

        Bir şirketi kalıcı olarak (hard) silmek, ona FK ile bağlı tüm
        satırları (kullanıcılar, birimler, belgeler, ...) sahipsiz
        bırakırdı; soft delete geçmişi bozulmadan korur ve askıya alınmış
        bir şirketin verilerinin yine de denetlenebilmesini sağlar.
        """
        company.is_deleted = True
        company.is_active = False
        await self.db.flush()
        return company
