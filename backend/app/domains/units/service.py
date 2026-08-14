from typing import List, Tuple
from uuid import uuid4

from app.api.exceptions.conflict import ConflictException
from app.api.exceptions.not_found import NotFoundException
from app.domains.units.model.unit_membership_model import UnitMembershipModel
from app.domains.units.model.unit_model import UnitModel
from app.domains.units.repository import UnitMembershipRepository, UnitRepository
from app.domains.units.schema.unit_schema import UnitCreate, UnitUpdate
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository


class UnitService:
    """Service executing unit-management business rules (create/list/update/delete).

    Every method takes an explicit `company_id` -- units are company-scoped
    (see `UnitModel`'s docstring): two companies may both define an "İnsan
    Kaynakları" unit without conflict.
    """

    def __init__(self, repository: UnitRepository):
        self.repository = repository

    async def create_unit(self, schema: UnitCreate, company_id: str) -> UnitModel:
        """Create a new routable unit, rejecting a duplicate name within `company_id`."""
        existing = await self.repository.get_by_name(schema.name, company_id)
        if existing:
            raise ConflictException(message="Bu isimde bir birim zaten mevcut.")

        unit = UnitModel(
            id=str(uuid4()),
            company_id=company_id,
            name=schema.name,
            description=schema.description,
            is_active=True,
        )
        return await self.repository.create(unit)

    async def get_unit_by_id(self, unit_id: str, company_id: str) -> UnitModel:
        """Fetch a unit by ID within `company_id`, raising NotFoundException if not present."""
        unit = await self.repository.get_by_id(unit_id, company_id)
        if not unit:
            raise NotFoundException(message="Birim bulunamadı.")
        return unit

    async def list_units(self, company_id: str) -> List[UnitModel]:
        """Fetch every unit of `company_id`, active or not."""
        return await self.repository.list_all(company_id)

    async def update_unit(self, unit_id: str, schema: UnitUpdate, company_id: str) -> UnitModel:
        """Update a unit's name/description/active status.

        Verifies name uniqueness (within `company_id`) when the name is
        being changed.
        """
        unit = await self.get_unit_by_id(unit_id, company_id)

        update_dict = schema.model_dump(exclude_unset=True)
        if "name" in update_dict and update_dict["name"] != unit.name:
            existing = await self.repository.get_by_name(update_dict["name"], company_id)
            if existing:
                raise ConflictException(message="Bu isimde bir birim zaten mevcut.")

        return await self.repository.update(unit, update_dict)

    async def delete_unit(self, unit_id: str, company_id: str) -> None:
        """Permanently delete a unit by ID, scoped to `company_id`."""
        deleted = await self.repository.delete(unit_id, company_id)
        if not deleted:
            raise NotFoundException(message="Birim bulunamadı.")


class UnitMembershipService:
    """Service executing unit-membership business rules (see `UnitMembershipModel`).

    Backs both `/units/{id}/members` (management) and `/units/{id}/
    suggested-recipients` (read-only, same underlying ranked listing) --
    the AI-suggested-recipients feature is exactly "who is in the unit
    routing already picked", no separate model or endpoint logic needed.
    """

    def __init__(
        self,
        membership_repository: UnitMembershipRepository,
        unit_repository: UnitRepository,
        user_repository: UserRepository,
    ):
        self.membership_repository = membership_repository
        self.unit_repository = unit_repository
        self.user_repository = user_repository

    async def add_member(
        self, unit_id: str, user_id: str, company_id: str, is_primary: bool, role_in_unit: str | None
    ) -> UnitMembershipModel:
        """Add `user_id` to `unit_id`, rejecting a duplicate membership or an unknown user."""
        unit = await self.unit_repository.get_by_id(unit_id, company_id)
        if unit is None:
            raise NotFoundException(message="Birim bulunamadı.")

        user = await self.user_repository.get_by_id_in_company(user_id, company_id)
        if user is None:
            raise NotFoundException(message="Kullanıcı bulunamadı.")

        existing = await self.membership_repository.get(unit_id, user_id, company_id)
        if existing is not None:
            raise ConflictException(message="Kullanıcı zaten bu birimin üyesi.")

        if is_primary:
            await self.membership_repository.clear_primary_for_user(user_id, company_id)

        membership = UnitMembershipModel(
            id=str(uuid4()),
            company_id=company_id,
            unit_id=unit_id,
            user_id=user_id,
            is_primary=is_primary,
            role_in_unit=role_in_unit,
        )
        return await self.membership_repository.create(membership)

    async def remove_member(self, unit_id: str, user_id: str, company_id: str) -> None:
        """Remove `user_id` from `unit_id`."""
        deleted = await self.membership_repository.delete(unit_id, user_id, company_id)
        if not deleted:
            raise NotFoundException(message="Üyelik bulunamadı.")

    async def list_members(
        self, unit_id: str, company_id: str
    ) -> List[Tuple[UnitMembershipModel, UserModel]]:
        """List `unit_id`'s members, ranked for suggestion (primary, then leads, then the rest).

        Raises NotFoundException if `unit_id` doesn't exist within `company_id`
        -- an empty membership list and a nonexistent unit must not look the
        same to the caller.
        """
        unit = await self.unit_repository.get_by_id(unit_id, company_id)
        if unit is None:
            raise NotFoundException(message="Birim bulunamadı.")
        return await self.membership_repository.list_for_unit(unit_id, company_id)
