from typing import List
from uuid import uuid4

from app.api.exceptions.conflict import ConflictException
from app.api.exceptions.not_found import NotFoundException
from app.api.exceptions.validation import ValidationException
from app.core.enums.user_role import UserRole
from app.domains.companies.model.company_model import CompanyModel
from app.domains.companies.repository import CompanyRepository
from app.domains.companies.schema.company_schema import CompanyCreate, CompanyUpdate
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository


class CompanyService:
    """Şirket yönetimi iş kurallarını uygulayan servis.

    Tasarım gereği yalnızca root'a özeldir: her metot, çağıranın router
    katmanında zaten ROOT olarak (veya okuma/analitik yolları için o
    şirketin kendi ADMIN'i olarak) yetkilendirildiğini varsayar -- bu
    servis yetkilendirmeyi değil, iş kurallarının değişmezlerini (slug
    benzersizliği, admin atama kuralları) uygular.
    """

    def __init__(self, repository: CompanyRepository, user_repository: UserRepository):
        self.repository = repository
        self.user_repository = user_repository

    async def create_company(self, schema: CompanyCreate, created_by: str) -> CompanyModel:
        """Yeni bir kiracı şirket oluşturur; yinelenen slug'ı reddeder."""
        existing = await self.repository.get_by_slug(schema.slug)
        if existing:
            raise ConflictException(message="Bu kısa ada (slug) sahip bir şirket zaten mevcut.")

        company = CompanyModel(
            id=str(uuid4()),
            name=schema.name,
            slug=schema.slug,
            tax_number=schema.tax_number,
            is_active=True,
            is_deleted=False,
            settings={},
            created_by=created_by,
        )
        return await self.repository.create(company)

    async def get_company_by_id(self, company_id: str) -> CompanyModel:
        """ID ile bir şirketi getirir; mevcut değilse veya silinmişse NotFoundException fırlatır."""
        company = await self.repository.get_by_id(company_id)
        if not company or company.is_deleted:
            raise NotFoundException(message="Şirket bulunamadı.")
        return company

    async def list_companies(self, *, page: int, size: int) -> tuple[List[CompanyModel], int]:
        """Silinmemiş şirketleri sayfalanmış şekilde getirir."""
        offset = (page - 1) * size
        companies = await self.repository.list_all(offset=offset, limit=size)
        total = await self.repository.count_all()
        return companies, total

    async def update_company(self, company_id: str, schema: CompanyUpdate) -> CompanyModel:
        """Bir şirketin ad/vergi numarası/aktiflik bayrağı/ayarlarını günceller."""
        company = await self.get_company_by_id(company_id)
        update_dict = schema.model_dump(exclude_unset=True)
        return await self.repository.update(company, update_dict)

    async def delete_company(self, company_id: str) -> None:
        """Bir şirketi soft-delete eder ve pasifleştirir."""
        company = await self.get_company_by_id(company_id)
        await self.repository.soft_delete(company)

    async def assign_admin(self, company_id: str, user_id: str) -> UserModel:
        """Bu şirketin mevcut bir kullanıcısını ADMIN'e yükseltir.

        Kullanıcı zaten hedef şirkete ait olmalıdır -- başka bir şirketten
        yabancı bir kullanıcıyı admin olarak atamak, onu sessizce kiracı
        sınırının ötesine taşırdı; bu tam olarak tüm kiracılık modelinin
        önlemek için var olduğu türden örtük, kiracılar arası bir yazma
        işlemidir. Root, kullanıcıyı yükseltmeden önce onun bu şirkete
        (ör. davet akışıyla) oluşturulduğundan/davet edildiğinden emin
        olmalıdır.
        """
        company = await self.get_company_by_id(company_id)
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            raise NotFoundException(message="Kullanıcı bulunamadı.")
        if user.company_id != company.id:
            raise ValidationException(
                message="Kullanıcı bu şirkete ait değil; önce kullanıcıyı şirkete davet edin."
            )
        return await self.user_repository.update(user, {"role": UserRole.ADMIN.value})
