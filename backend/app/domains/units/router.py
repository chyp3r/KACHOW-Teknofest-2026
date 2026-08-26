from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_auth_if_enabled, require_roles
from app.api.responses import APIResponse, SuccessResponse
from app.core.enums.user_role import UserRole
from app.domains.audit.repository import AuditLogRepository
from app.domains.audit.service import AuditService
from app.domains.units.repository import UnitMembershipRepository, UnitRepository
from app.domains.units.schema.unit_membership_schema import UnitMemberCreate, UnitMemberResponse
from app.domains.units.schema.unit_schema import UnitCreate, UnitResponse, UnitUpdate
from app.domains.units.service import UnitMembershipService, UnitService
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.infrastructure.database.session import get_db

router = APIRouter(prefix="/units", tags=["units"])


def _audit_service(db: AsyncSession) -> AuditService:
    return AuditService(AuditLogRepository(db))


@router.get("", response_model=APIResponse[List[UnitResponse]])
async def list_units(
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Çağıranın şirketindeki her birimi listeler (aktif ve pasif) -- yapay
    zekanın yönlendirme önerilerinin kendisi yalnızca aktif alt kümeyi
    dikkate alır (bkz. ``app.domains.units.provider``); bu uç nokta bir
    yönetici arayüzünün pasif bir birimi inceleyip yeniden aktif
    edebilmesi için ikisini de döndürür."""
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
    """Çağıranın şirketi içinde yönlendirilebilir yeni bir birim oluşturur (yalnızca Admin/Manager)."""
    repository = UnitRepository(db)
    service = UnitService(repository)
    unit = await service.create_unit(schema, current_user.company_id)
    await _audit_service(db).record(
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="unit:create",
        resource_type="unit",
        resource_id=unit.id,
        after={"name": unit.name},
    )
    response_data = UnitResponse.model_validate(unit)
    return SuccessResponse(data=response_data)


@router.patch("/{unit_id}", response_model=APIResponse[UnitResponse])
async def update_unit(
    unit_id: str,
    schema: UnitUpdate,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Bir birimin adını, açıklamasını veya aktiflik durumunu günceller (yalnızca Admin/Manager)."""
    repository = UnitRepository(db)
    service = UnitService(repository)
    unit = await service.update_unit(unit_id, schema, current_user.company_id)
    await _audit_service(db).record(
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="unit:update",
        resource_type="unit",
        resource_id=unit_id,
        after=schema.model_dump(exclude_unset=True, mode="json"),
    )
    response_data = UnitResponse.model_validate(unit)
    return SuccessResponse(data=response_data)


@router.delete("/{unit_id}", response_model=APIResponse[None])
async def delete_unit(
    unit_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Bir birimi kalıcı olarak siler (yalnızca Admin/Manager)."""
    repository = UnitRepository(db)
    service = UnitService(repository)
    await service.delete_unit(unit_id, current_user.company_id)
    await _audit_service(db).record(
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="unit:delete",
        resource_type="unit",
        resource_id=unit_id,
    )
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
    """Bir şirket kullanıcısını bir birime ekler (yalnızca Admin/Manager)."""
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
    """Bir kullanıcıyı bir birimden çıkarır (yalnızca Admin/Manager)."""
    service = _membership_service(db)
    await service.remove_member(unit_id, user_id, current_user.company_id)
    return SuccessResponse(data=None)


@router.get("/{unit_id}/members", response_model=APIResponse[List[UnitMemberResponse]])
async def list_unit_members(
    unit_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Bir birimin üyelerini sıralanmış şekilde listeler (önce birincil, sonra sorumlular, sonra geri kalanlar)."""
    service = _membership_service(db)
    members = await service.list_members(unit_id, current_user.company_id)
    return SuccessResponse(data=_member_responses(members))


@router.get("/{unit_id}/suggested-recipients", response_model=APIResponse[List[UnitMemberResponse]])
async def suggested_recipients(
    unit_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Yapay zeka tarafından önerilen taslak alıcıları: yönlendirmenin
    seçtiği birimin üyeleri.

    Mevcut yönlendirme kararını tamamen yeniden kullanır -- burada yeni bir
    yapay zeka çağrısı yoktur. Çağıranın zaten `GET /units` ile eşleştirilmiş,
    yönlendirilen `destination` birim adından (`POST /documents/draft`'ın
    yanıtı veya `POST /routing/suggest`) gelen bir `unit_id`'si vardır; bu
    yalnızca o birimin kendi üyeliğini `GET /units/{id}/members`'ın yaptığı
    aynı şekilde sıralar (önce birincil, sonra sorumlular, sonra herkes),
    ki bu da bir birim zaten belirlendikten sonra "önerilen alıcılar"ın tam
    olarak ne anlama geldiğidir.
    """
    service = _membership_service(db)
    members = await service.list_members(unit_id, current_user.company_id)
    return SuccessResponse(data=_member_responses(members))
