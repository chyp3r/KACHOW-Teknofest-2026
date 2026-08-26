from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_db, get_owner_db
from app.api.rate_limit import rate_limit
from app.api.responses import APIResponse, SuccessResponse
from app.domains.users.schema.user_schema import UserCreate, UserUpdate, PasswordChangeRequest, UserResponse
from app.domains.users.schema.invited_email import InvitedEmailCreate, InvitedEmailResponse
from app.domains.users.schema.favorite_schema import FavoriteCreateRequest, FavoriteResponse
from app.domains.users.schema.user_search_schema import UserSearchResult
from app.domains.users.repository import UserFavoriteRepository, UserRepository
from app.domains.users.service import UserService
from app.domains.users.favorites_service import FavoriteService
from app.domains.users.model.user_model import UserModel
from app.api.dependency import get_authz_service, get_current_user, require_auth_if_enabled, require_roles, subject_from_user
from app.core.authz.attributes import Resource
from app.core.authz.model.permission_grant_model import PermissionGrantModel
from app.core.authz.repository import PermissionGrantRepository
from app.core.authz.schema import PermissionGrantCreate, PermissionGrantResponse
from app.core.authz.service import AuthzService
from app.core.enums.user_role import UserRole
from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.domains.audit.repository import AuditLogRepository
from app.domains.audit.service import AuditService
from app.shared.dto.pagination import PaginatedResponse, PaginationParam

router = APIRouter(prefix="/users", tags=["users"])


def _audit_service(db: AsyncSession) -> AuditService:
    return AuditService(AuditLogRepository(db))


def _favorite_service(db: AsyncSession) -> FavoriteService:
    return FavoriteService(UserFavoriteRepository(db), UserRepository(db))

@router.post("", response_model=APIResponse[UserResponse])
async def register(schema: UserCreate, db: AsyncSession = Depends(get_owner_db)):
    """Sistemde yeni bir kullanıcı hesabı kaydeder, e-posta davet beyaz listesini doğrular.

    Tasarım gereği kimlik doğrulaması yoktur -- bunun yerine kayıt davet
    tarafından kapılanır (bkz. `UserService.register_user`), ve yeni
    hesabın hem rolünü hem de şirketini belirleyen davettir, istek gövdesi
    asla değil.

    `get_db` yerine `get_owner_db` kullanılır: davet araması `email` ile
    yapılır, sistem genelinde benzersizdir (`InvitedEmailModel.email`,
    şirket bazında değil), bu yüzden davet (ve ait olduğu şirket)
    bulunana kadar satır düzeyinde bir güvenlik politikasını kapsayacak
    bir kiracı bağlamı henüz yoktur -- `auth/router.py::login` ile aynı
    gerekçe.
    """
    repository = UserRepository(db)
    service = UserService(repository)
    user = await service.register_user(schema)
    response_data = UserResponse.model_validate(user)
    return SuccessResponse(data=response_data)

@router.post("/invitations", response_model=APIResponse[InvitedEmailResponse])
async def invite_user(
    schema: InvitedEmailCreate,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db)
):
    """Bir e-posta adresini önceden tanımlanmış bir rolle çağıranın kendi
    şirketine davet eder/beyaz listeye alır (yalnızca Admin/Manager)."""
    repository = UserRepository(db)
    service = UserService(repository)
    invite = await service.invite_user_email(schema, current_user.company_id)
    response_data = InvitedEmailResponse.model_validate(invite)
    return SuccessResponse(data=response_data)

@router.get("", response_model=APIResponse[List[UserResponse]])
async def list_users(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    role: Optional[UserRole] = Query(default=None),
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db)
):
    """Çağıranın kendi şirketinin kullanıcılarını sayfalanmış ve role göre filtrelenmiş şekilde getirir (yalnızca Admin/Manager)."""
    repository = UserRepository(db)
    service = UserService(repository)
    role_str = role.value if role else None
    users = await service.get_users(current_user.company_id, skip=skip, limit=limit, role=role_str)
    response_data = [UserResponse.model_validate(u) for u in users]
    return SuccessResponse(data=response_data)

@router.get("/me", response_model=APIResponse[UserResponse])
async def get_me(current_user: UserModel = Depends(get_current_user)):
    """Şu anda kimliği doğrulanmış kullanıcının profil bilgilerini getirir."""
    response_data = UserResponse.model_validate(current_user)
    return SuccessResponse(data=response_data)


# NOT: /search ve /me/... aşağıdaki GET /{user_id}'den önce kaydedilmelidir
# -- FastAPI rotaları kayıt sırasına göre eşleştirir ve "/search" gibi tek
# segmentli bir yol, aksi halde o rota önce kaydedildiği için
# "/{user_id}" (user_id="search") tarafından yutulurdu.
@router.get(
    "/search",
    response_model=None,
    dependencies=[Depends(rate_limit(max_requests=30, window_seconds=60, key_prefix="user_search"))],
)
async def search_users(
    q: Optional[str] = Query(default=None, min_length=2, max_length=100),
    unit_id: Optional[str] = Query(default=None),
    role: Optional[UserRole] = Query(default=None),
    pagination: PaginationParam = Depends(),
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Mesajlaşma/artefakt transferi alıcı seçicisi için çağıranın kendi
    şirketinin kullanıcılarında arama yapar. `q`, bunun şirket geneli bir
    kullanıcı listeleme aracına dönüşmesini engellemek için en az 2 karakter
    gerektirir (üzerine hız sınırlaması da eklenmiştir -- bkz.
    `rate_limit`'in kendi docstring'i). Sonuçlar, ne olursa olsun her zaman
    RLS + açık `company_id` filtresi ile şirket bazlıdır.
    """
    service = UserService(UserRepository(db))
    favorite_repository = UserFavoriteRepository(db)
    role_str = role.value if role else None
    items, total = await service.search_users(
        current_user.company_id,
        q=q,
        unit_id=unit_id,
        role=role_str,
        skip=pagination.offset,
        limit=min(pagination.limit, 50),
    )
    page_items = []
    for user, unit_name in items:
        is_favorite = await favorite_repository.is_favorite(current_user.id, user.id, current_user.company_id)
        page_items.append(
            UserSearchResult(
                id=user.id,
                username=user.username,
                email=user.email,
                role=user.role,
                unit_name=unit_name,
                is_favorite=is_favorite,
            ).model_dump(mode="json")
        )
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0
    return SuccessResponse(
        data=PaginatedResponse(
            items=page_items, total=total, page=pagination.page, size=pagination.size, pages=pages
        ).model_dump()
    )


def _favorite_response(favorite, user: UserModel) -> FavoriteResponse:
    return FavoriteResponse(
        id=favorite.id,
        favorite_user_id=favorite.favorite_user_id,
        username=user.username,
        email=user.email,
        note=favorite.note,
        created_at=favorite.created_at,
    )


@router.get("/me/favorites", response_model=None)
async def list_my_favorites(
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Çağıranın kendi favorileri, en son favorilenen önce."""
    items = await _favorite_service(db).list_favorites(current_user.company_id, current_user)
    return SuccessResponse(
        data=[_favorite_response(favorite, user).model_dump(mode="json") for favorite, user in items]
    )


@router.post("/me/favorites", response_model=None)
async def add_my_favorite(
    request: FavoriteCreateRequest,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Bir şirket kullanıcısını çağıranın kendi favorilerine ekler."""
    favorite, user = await _favorite_service(db).add_favorite(
        current_user.company_id, current_user, request.user_id, request.note
    )
    return SuccessResponse(data=_favorite_response(favorite, user).model_dump(mode="json"))


@router.delete("/me/favorites/{user_id}", response_model=None)
async def remove_my_favorite(
    user_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Bir kullanıcıyı çağıranın kendi favorilerinden çıkarır."""
    await _favorite_service(db).remove_favorite(current_user.company_id, current_user, user_id)
    return SuccessResponse(data={"removed": True})


@router.get("/{user_id}", response_model=APIResponse[UserResponse])
async def get_user(
    user_id: str,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Belirli bir kullanıcının bilgilerini getirir. Kimliği doğrulanmış
    kullanıcı, o kullanıcının kendi şirketinin Admin/Manager'ı olmadığı
    sürece yalnızca kendisini getirebilir (ROOT burada örtük olarak şirketler
    arası değildir -- root'un şirket bazlı görünümleri için `/companies`
    rotalarına bakın)."""
    repository = UserRepository(db)
    service = UserService(repository)

    if current_user.id == user_id:
        user = await service.get_user_by_id(user_id)
    else:
        is_admin_or_manager = current_user.role in [UserRole.ADMIN.value, UserRole.MANAGER.value]
        if not is_admin_or_manager:
            raise AuthorizationException(message="Bu kullanıcının bilgilerini görüntüleme yetkiniz yok.")
        user = await service.get_user_by_id_in_company(user_id, current_user.company_id)

    response_data = UserResponse.model_validate(user)
    return SuccessResponse(data=response_data)

@router.put("/{user_id}", response_model=APIResponse[UserResponse])
async def update_user(
    user_id: str,
    schema: UserUpdate,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Bir kullanıcının profil bilgilerini günceller. Rol veya durum değişiklikleri Admin yetkisi gerektirir."""
    is_admin = current_user.role == UserRole.ADMIN.value
    is_self = current_user.id == user_id

    # Yetkileri uygula
    if not is_admin and not is_self:
        raise AuthorizationException(message="Bu kullanıcının bilgilerini güncelleme yetkiniz yok.")

    # Admin olmayanlar için alan güncellemelerini kısıtla
    if not is_admin:
        if schema.role is not None or schema.is_active is not None or schema.clearance_level is not None:
            raise AuthorizationException(
                message="Rol, hesap durumu veya yetki seviyesini yalnızca yöneticiler güncelleyebilir."
            )

    repository = UserRepository(db)
    service = UserService(repository)
    updated_user = await service.update_user(user_id, schema, current_user.company_id)
    response_data = UserResponse.model_validate(updated_user)
    return SuccessResponse(data=response_data)

@router.post("/me/password", response_model=APIResponse[None])
async def change_my_password(
    schema: PasswordChangeRequest,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Doğrulamadan sonra şu anda giriş yapmış kullanıcının parolasını günceller."""
    repository = UserRepository(db)
    service = UserService(repository)
    await service.change_password(current_user.id, schema)
    return SuccessResponse(data=None)

@router.delete("/{user_id}/soft", response_model=APIResponse[None])
async def soft_delete(
    user_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db)
):
    """is_deleted bayrağını ayarlayarak kullanıcı hesabını geri alınabilir şekilde siler (yalnızca Admin, kendi şirketi)."""
    repository = UserRepository(db)
    service = UserService(repository)
    await service.soft_delete_user(user_id, current_user.company_id)
    return SuccessResponse(data=None)

@router.delete("/{user_id}/hard", response_model=APIResponse[None])
async def hard_delete(
    user_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db)
):
    """Kullanıcı kaydını veritabanından kalıcı olarak siler (yalnızca Admin, kendi şirketi)."""
    repository = UserRepository(db)
    service = UserService(repository)
    await service.hard_delete_user(user_id, current_user.company_id)
    return SuccessResponse(data=None)


@router.post("/{user_id}/permissions", response_model=APIResponse[PermissionGrantResponse])
async def grant_permission(
    user_id: str,
    schema: PermissionGrantCreate,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
    authz: AuthzService = Depends(get_authz_service),
):
    """Bir şirket kullanıcısına bir yetki devreder (yalnızca Admin/Manager).

    Yetki yükseltmesi olmaması: yetkiyi verenin kendisi, o eylemi başka
    birine devredebilmeden önce ``schema.action`` için yetkilendirilmiş
    olmalıdır (kendi kimliği kaynağın sahibi yerine geçerek kontrol edilir)
    -- yalnızca devredilmiş bir ``document:delete`` yetkisine sahip bir
    yönetici, kendisine hiç verilmediği için ``draft:send`` yetkisini
    devredemez. Yerleşik ADMIN/MANAGER rol kuralları bugün tanımlı her
    eylemi zaten kapsadığından (bkz. ``app.core.authz.rules.BUILTIN_RULES``),
    bu kontrol yalnızca bir yöneticinin kendi yetkileri rolden değil
    devirden türetildiğinde fiilen kısıtlamaya başlar.
    """
    user_repository = UserRepository(db)
    target = await user_repository.get_by_id_in_company(user_id, current_user.company_id)
    if target is None:
        raise NotFoundException(message="Kullanıcı bulunamadı.")

    self_check_resource = Resource(
        type=schema.resource_type, company_id=current_user.company_id, owner_id=current_user.id
    )
    granter_decision = await authz.authorize(
        subject_from_user(current_user), schema.action, self_check_resource
    )
    if not granter_decision.permit:
        raise AuthorizationException(message="Sahip olmadığınız bir yetkiyi devredemezsiniz.")

    grant_repository = PermissionGrantRepository(db)
    grant = await grant_repository.create(
        PermissionGrantModel(
            company_id=current_user.company_id,
            subject_type="user",
            subject_id=user_id,
            action=schema.action,
            resource_type=schema.resource_type,
            resource_selector=schema.resource_selector,
            effect=schema.effect,
            priority=schema.priority,
            valid_from=schema.valid_from,
            valid_until=schema.valid_until,
            granted_by=current_user.id,
            reason=schema.reason,
        )
    )
    await authz.invalidate_company(current_user.company_id)
    await _audit_service(db).record(
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="permission:grant",
        resource_type="permission_grant",
        resource_id=grant.id,
        after={"subject_id": user_id, "action": schema.action, "effect": schema.effect},
    )
    return SuccessResponse(data=PermissionGrantResponse.model_validate(grant).model_dump(mode="json"))


@router.get("/{user_id}/permissions", response_model=APIResponse[List[PermissionGrantResponse]])
async def list_permissions(
    user_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Bir şirket kullanıcısına açıkça verilmiş, geri alınmamış her yetkiyi listeler (yalnızca Admin/Manager)."""
    grant_repository = PermissionGrantRepository(db)
    grants = await grant_repository.list_for_user(current_user.company_id, user_id)
    return SuccessResponse(
        data=[PermissionGrantResponse.model_validate(g).model_dump(mode="json") for g in grants]
    )


@router.delete("/permissions/{grant_id}", response_model=APIResponse[None])
async def revoke_permission(
    grant_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
    authz: AuthzService = Depends(get_authz_service),
):
    """Bir yetki devrini geri alır (yalnızca Admin/Manager, kendi şirketi).

    Geri alınan satır silinmez, saklanır (bkz.
    ``PermissionGrantModel.revoked_at``'ın docstring'i) -- kendi denetim izi.
    """
    grant_repository = PermissionGrantRepository(db)
    revoked = await grant_repository.revoke(grant_id, current_user.company_id)
    if not revoked:
        raise NotFoundException(message="Yetki bulunamadı ya da zaten geri alınmış.")
    await authz.invalidate_company(current_user.company_id)
    await _audit_service(db).record(
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="permission:revoke",
        resource_type="permission_grant",
        resource_id=grant_id,
    )
    return SuccessResponse(data=None)
