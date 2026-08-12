from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.units.model.unit_model import UnitModel


class UnitRepository:
    """SOTA Repository for SQLAlchemy database transactions regarding Units."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, unit_id: str) -> Optional[UnitModel]:
        """Fetch a unit by primary key ID."""
        result = await self.db.execute(select(UnitModel).where(UnitModel.id == unit_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[UnitModel]:
        """Fetch a unit by its unique name."""
        result = await self.db.execute(select(UnitModel).where(UnitModel.name == name))
        return result.scalar_one_or_none()

    async def list_all(self) -> List[UnitModel]:
        """Fetch every unit, active or not, ordered by name."""
        result = await self.db.execute(select(UnitModel).order_by(UnitModel.name))
        return list(result.scalars().all())

    async def list_active(self) -> List[UnitModel]:
        """Fetch only the units currently eligible for routing suggestions."""
        result = await self.db.execute(
            select(UnitModel).where(UnitModel.is_active == True).order_by(UnitModel.name)  # noqa: E712
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

    async def delete(self, unit_id: str) -> bool:
        """Permanently remove a unit record from the database."""
        result = await self.db.execute(delete(UnitModel).where(UnitModel.id == unit_id))
        await self.db.flush()
        return result.rowcount > 0
