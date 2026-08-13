from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.units.model.unit_model import UnitModel


class UnitRepository:
    """SOTA Repository for SQLAlchemy database transactions regarding Units.

    Every method takes an explicit `company_id` and filters on it -- see
    `app.domains.documents.repository.DocumentRepository`'s docstring for
    the same convention and reasoning.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, unit_id: str, company_id: str) -> Optional[UnitModel]:
        """Fetch a unit by primary key ID, scoped to `company_id`."""
        result = await self.db.execute(
            select(UnitModel).where(UnitModel.id == unit_id, UnitModel.company_id == company_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str, company_id: str) -> Optional[UnitModel]:
        """Fetch a unit by name within `company_id` (uniqueness is per-company, not global)."""
        result = await self.db.execute(
            select(UnitModel).where(UnitModel.name == name, UnitModel.company_id == company_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self, company_id: str) -> List[UnitModel]:
        """Fetch every unit of `company_id`, active or not, ordered by name."""
        result = await self.db.execute(
            select(UnitModel)
            .where(UnitModel.company_id == company_id)
            .order_by(UnitModel.name)
        )
        return list(result.scalars().all())

    async def list_active(self, company_id: str) -> List[UnitModel]:
        """Fetch only `company_id`'s units currently eligible for routing suggestions."""
        result = await self.db.execute(
            select(UnitModel)
            .where(UnitModel.company_id == company_id, UnitModel.is_active == True)  # noqa: E712
            .order_by(UnitModel.name)
        )
        return list(result.scalars().all())

    async def create(self, unit: UnitModel) -> UnitModel:
        """Persist a new unit record in the database."""
        self.db.add(unit)
        await self.db.flush()
        return unit

    async def update(self, unit: UnitModel, update_data: dict) -> UnitModel:
        """Update attributes of a unit model and flush."""
        for field, value in update_data.items():
            if hasattr(unit, field) and value is not None:
                setattr(unit, field, value)
        await self.db.flush()
        return unit

    async def delete(self, unit_id: str, company_id: str) -> bool:
        """Permanently remove a unit record from the database, scoped to `company_id`."""
        result = await self.db.execute(
            delete(UnitModel).where(UnitModel.id == unit_id, UnitModel.company_id == company_id)
        )
        await self.db.flush()
        return result.rowcount > 0
