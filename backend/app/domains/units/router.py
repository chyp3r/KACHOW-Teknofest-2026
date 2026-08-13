from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_auth_if_enabled, require_roles
from app.api.responses import APIResponse, SuccessResponse
from app.core.enums.user_role import UserRole
from app.domains.units.repository import UnitRepository
from app.domains.units.schema.unit_schema import UnitCreate, UnitResponse, UnitUpdate
from app.domains.units.service import UnitService
from app.domains.users.model.user_model import UserModel
from app.infrastructure.database.session import get_db

router = APIRouter(prefix="/units", tags=["units"])


@router.get("", response_model=APIResponse[List[UnitResponse]])
async def list_units(
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """List every unit of the caller's company (active and inactive) -- the
    AI's routing suggestions themselves only ever consider the active
    subset (see ``app.domains.units.provider``); this endpoint returns both
    so an admin UI can review and reactivate a disabled unit."""
    repository = UnitRepository(db)
    service = UnitService(repository)
    units = await service.list_units(current_user.company_id)
    response_data = [UnitResponse.model_validate(u) for u in units]
    return SuccessResponse(data=response_data)


@router.post("", response_model=APIResponse[UnitResponse])
async def create_unit(
    schema: UnitCreate,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Create a new routable unit within the caller's company (Admin/Manager only)."""
    repository = UnitRepository(db)
    service = UnitService(repository)
    unit = await service.create_unit(schema, current_user.company_id)
    response_data = UnitResponse.model_validate(unit)
    return SuccessResponse(data=response_data)


@router.patch("/{unit_id}", response_model=APIResponse[UnitResponse])
async def update_unit(
    unit_id: str,
    schema: UnitUpdate,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Update a unit's name, description or active status (Admin/Manager only)."""
    repository = UnitRepository(db)
    service = UnitService(repository)
    unit = await service.update_unit(unit_id, schema, current_user.company_id)
    response_data = UnitResponse.model_validate(unit)
    return SuccessResponse(data=response_data)


@router.delete("/{unit_id}", response_model=APIResponse[None])
async def delete_unit(
    unit_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a unit (Admin/Manager only)."""
    repository = UnitRepository(db)
    service = UnitService(repository)
    await service.delete_unit(unit_id, current_user.company_id)
    return SuccessResponse(data=None)
