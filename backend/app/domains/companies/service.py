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
    """Service executing company-management business rules.

    Root-only by construction: every method assumes the caller has already
    been authorized as ROOT (or, for the read/analytics paths, as that
    company's own ADMIN) at the router layer -- this service enforces
    business invariants (slug uniqueness, admin-assignment rules), not
    authorization.
    """

    def __init__(self, repository: CompanyRepository, user_repository: UserRepository):
        self.repository = repository
        self.user_repository = user_repository

    async def create_company(self, schema: CompanyCreate, created_by: str) -> CompanyModel:
        """Create a new tenant company, rejecting a duplicate slug."""
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
        """Fetch a company by ID, raising NotFoundException if not present or deleted."""
        company = await self.repository.get_by_id(company_id)
        if not company or company.is_deleted:
            raise NotFoundException(message="Şirket bulunamadı.")
        return company

    async def list_companies(self, *, page: int, size: int) -> tuple[List[CompanyModel], int]:
        """Fetch non-deleted companies, paginated."""
        offset = (page - 1) * size
        companies = await self.repository.list_all(offset=offset, limit=size)
        total = await self.repository.count_all()
        return companies, total

    async def update_company(self, company_id: str, schema: CompanyUpdate) -> CompanyModel:
        """Update a company's name/tax number/active flag/settings."""
        company = await self.get_company_by_id(company_id)
        update_dict = schema.model_dump(exclude_unset=True)
        return await self.repository.update(company, update_dict)

    async def delete_company(self, company_id: str) -> None:
        """Soft-delete a company and deactivate it."""
        company = await self.get_company_by_id(company_id)
        await self.repository.soft_delete(company)

    async def assign_admin(self, company_id: str, user_id: str) -> UserModel:
        """Promote an existing user of this company to ADMIN.

        The user must already belong to the target company -- assigning a
        stranger from another company as admin would silently move them
        across the tenant boundary, which is exactly the kind of implicit
        cross-tenant write the whole tenancy model exists to prevent. Root
        must first ensure the user was created/invited into this company
        (e.g. via the invite flow) before promoting them.
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
