from typing import List
from uuid import uuid4

from app.api.exceptions.conflict import ConflictException
from app.api.exceptions.not_found import NotFoundException
from app.domains.units.model.unit_model import UnitModel
from app.domains.units.repository import UnitRepository
from app.domains.units.schema.unit_schema import UnitCreate, UnitUpdate


class UnitService:
    """Service executing unit-management business rules (create/list/update/delete)."""

    def __init__(self, repository: UnitRepository):
        self.repository = repository

    async def create_unit(self, schema: UnitCreate) -> UnitModel:
        """Create a new routable unit, rejecting a duplicate name."""
        existing = await self.repository.get_by_name(schema.name)
        if existing:
            raise ConflictException(message="Bu isimde bir birim zaten mevcut.")

        unit = UnitModel(
            id=str(uuid4()),
            name=schema.name,
            description=schema.description,
            is_active=True,
        )
        return await self.repository.create(unit)

    async def get_unit_by_id(self, unit_id: str) -> UnitModel:
        """Fetch a unit by ID, raising NotFoundException if not present."""
        unit = await self.repository.get_by_id(unit_id)
        if not unit:
            raise NotFoundException(message="Birim bulunamadı.")
        return unit

    async def list_units(self) -> List[UnitModel]:
        """Fetch every unit, active or not."""
        return await self.repository.list_all()

    async def update_unit(self, unit_id: str, schema: UnitUpdate) -> UnitModel:
        """Update a unit's name/description/active status.

        Verifies name uniqueness when the name is being changed.
        """
        unit = await self.get_unit_by_id(unit_id)

        update_dict = schema.model_dump(exclude_unset=True)
        if "name" in update_dict and update_dict["name"] != unit.name:
            existing = await self.repository.get_by_name(update_dict["name"])
            if existing:
                raise ConflictException(message="Bu isimde bir birim zaten mevcut.")

        return await self.repository.update(unit, update_dict)

    async def delete_unit(self, unit_id: str) -> None:
        """Permanently delete a unit by ID."""
        deleted = await self.repository.delete(unit_id)
        if not deleted:
            raise NotFoundException(message="Birim bulunamadı.")
