from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.companies.model.company_model import CompanyModel


class CompanyRepository:
    """Repository for SQLAlchemy database transactions regarding Companies.

    Unlike every other repository in the system, this one is deliberately
    NOT company-scoped -- a company is the scoping unit itself, so listing
    and looking up companies is inherently a root-only, cross-tenant
    operation. Callers must gate access with ``require_roles(UserRole.ROOT)``
    (or the future ABAC ``system:*`` action) rather than relying on this
    repository to filter anything.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, company_id: str) -> Optional[CompanyModel]:
        """Fetch a company by primary key ID, including soft-deleted rows."""
        result = await self.db.execute(select(CompanyModel).where(CompanyModel.id == company_id))
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Optional[CompanyModel]:
        """Fetch a company by its unique slug."""
        result = await self.db.execute(select(CompanyModel).where(CompanyModel.slug == slug))
        return result.scalar_one_or_none()

    async def list_all(self, *, offset: int = 0, limit: int = 20) -> List[CompanyModel]:
        """Fetch non-deleted companies, paginated, ordered by name."""
        result = await self.db.execute(
            select(CompanyModel)
            .where(CompanyModel.is_deleted == False)  # noqa: E712
            .order_by(CompanyModel.name)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_all(self) -> int:
        """Count non-deleted companies."""
        result = await self.db.execute(
            select(func.count()).select_from(CompanyModel).where(CompanyModel.is_deleted == False)  # noqa: E712
        )
        return result.scalar_one()

    async def create(self, company: CompanyModel) -> CompanyModel:
        """Persist a new company record in the database."""
        self.db.add(company)
        await self.db.flush()
        return company

    async def update(self, company: CompanyModel, update_data: dict) -> CompanyModel:
        """Update attributes of a company model and flush."""
        for field, value in update_data.items():
            if hasattr(company, field) and value is not None:
                setattr(company, field, value)
        await self.db.flush()
        return company

    async def soft_delete(self, company: CompanyModel) -> CompanyModel:
        """Mark a company as deleted and inactive without removing the row.

        Hard-deleting a company would orphan every row that FKs to it
        (users, units, documents, ...); soft delete keeps history intact and
        lets a suspended company's data still be audited.
        """
        company.is_deleted = True
        company.is_active = False
        await self.db.flush()
        return company
