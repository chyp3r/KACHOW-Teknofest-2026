from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_auth_if_enabled, require_roles
from app.api.responses import APIResponse, SuccessResponse
from app.core.enums.user_role import UserRole
from app.domains.units.repository import UnitMembershipRepository, UnitRepository
from app.domains.units.schema.unit_membership_schema import UnitMemberCreate, UnitMemberResponse
from app.domains.units.schema.unit_schema import UnitCreate, UnitResponse, UnitUpdate
from app.domains.units.service import UnitMembershipService, UnitService
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
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


def _membership_service(db: AsyncSession) -> UnitMembershipService:
    return UnitMembershipService(
        membership_repository=UnitMembershipRepository(db),
        unit_repository=UnitRepository(db),
        user_repository=UserRepository(db),
    )


def _member_responses(members) -> List[UnitMemberResponse]:
    return [
        UnitMemberResponse(
            user_id=user.id,
            username=user.username,
            email=user.email,
            is_primary=membership.is_primary,
            role_in_unit=membership.role_in_unit,
        )
        for membership, user in members
    ]


@router.post("/{unit_id}/members", response_model=APIResponse[UnitMemberResponse])
async def add_unit_member(
    unit_id: str,
    schema: UnitMemberCreate,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Add a company user to a unit (Admin/Manager only)."""
    service = _membership_service(db)
    membership = await service.add_member(
        unit_id,
        schema.user_id,
        current_user.company_id,
        is_primary=schema.is_primary,
        role_in_unit=schema.role_in_unit,
    )
    user = await UserRepository(db).get_by_id_in_company(schema.user_id, current_user.company_id)
    return SuccessResponse(
        data=UnitMemberResponse(
            user_id=membership.user_id,
            username=user.username,
            email=user.email,
            is_primary=membership.is_primary,
            role_in_unit=membership.role_in_unit,
        )
    )


@router.delete("/{unit_id}/members/{user_id}", response_model=APIResponse[None])
async def remove_unit_member(
    unit_id: str,
    user_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Remove a user from a unit (Admin/Manager only)."""
    service = _membership_service(db)
    await service.remove_member(unit_id, user_id, current_user.company_id)
    return SuccessResponse(data=None)


@router.get("/{unit_id}/members", response_model=APIResponse[List[UnitMemberResponse]])
async def list_unit_members(
    unit_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """List a unit's members, ranked (primary first, then leads, then the rest)."""
    service = _membership_service(db)
    members = await service.list_members(unit_id, current_user.company_id)
    return SuccessResponse(data=_member_responses(members))


@router.get("/{unit_id}/suggested-recipients", response_model=APIResponse[List[UnitMemberResponse]])
async def suggested_recipients(
    unit_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """AI-suggested draft recipients: the members of the unit routing chose.

    Reuses the existing routing decision entirely -- no new AI call here.
    The caller already has `unit_id` from the routed `destination` unit name
    (`POST /documents/draft`'s response, or `POST /routing/suggest`) matched
    against `GET /units`; this just ranks that unit's own membership the
    same way `GET /units/{id}/members` does (primary, then leads, then
    everyone else), which is exactly what "suggested recipients" means once
    a unit has already been identified.
    """
    service = _membership_service(db)
    members = await service.list_members(unit_id, current_user.company_id)
    return SuccessResponse(data=_member_responses(members))
