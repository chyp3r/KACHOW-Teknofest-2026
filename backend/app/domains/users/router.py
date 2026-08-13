from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_db, get_owner_db
from app.api.responses import APIResponse, SuccessResponse
from app.domains.users.schema.user_schema import UserCreate, UserUpdate, PasswordChangeRequest, UserResponse
from app.domains.users.schema.invited_email import InvitedEmailCreate, InvitedEmailResponse
from app.domains.users.repository import UserRepository
from app.domains.users.service import UserService
from app.domains.users.model.user_model import UserModel
from app.api.dependency import get_authz_service, get_current_user, require_roles, subject_from_user
from app.core.authz.attributes import Resource
from app.core.authz.model.permission_grant_model import PermissionGrantModel
from app.core.authz.repository import PermissionGrantRepository
from app.core.authz.schema import PermissionGrantCreate, PermissionGrantResponse
from app.core.authz.service import AuthzService
from app.core.enums.user_role import UserRole
from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException

router = APIRouter(prefix="/users", tags=["users"])

@router.post("", response_model=APIResponse[UserResponse])
async def register(schema: UserCreate, db: AsyncSession = Depends(get_owner_db)):
    """Register a new user account in the system, validating the email invitation whitelist.

    Unauthenticated by design -- registration is invite-gated instead (see
    `UserService.register_user`), and the invite is what determines both
    the new account's role and its company, never the request body.

    Uses `get_owner_db`, not `get_db`: the invite lookup is by `email`,
    unique system-wide (`InvitedEmailModel.email`, not per company), so
    there is no tenant context yet to scope a row-level-security policy by
    until the invite (and the company it belongs to) is found -- same
    reasoning as `auth/router.py::login`.
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
    """Invite/whitelist an email address with a predefined role, into the
    caller's own company (Admin/Manager only)."""
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
    """Retrieve the caller's own company's users, paginated and role-filtered (Admin/Manager only)."""
    repository = UserRepository(db)
    service = UserService(repository)
    role_str = role.value if role else None
    users = await service.get_users(current_user.company_id, skip=skip, limit=limit, role=role_str)
    response_data = [UserResponse.model_validate(u) for u in users]
    return SuccessResponse(data=response_data)

@router.get("/me", response_model=APIResponse[UserResponse])
async def get_me(current_user: UserModel = Depends(get_current_user)):
    """Get profile details of the currently authenticated user."""
    response_data = UserResponse.model_validate(current_user)
    return SuccessResponse(data=response_data)

@router.get("/{user_id}", response_model=APIResponse[UserResponse])
async def get_user(
    user_id: str,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve details of a specific user. Authenticated user can only
    retrieve themselves, unless they are Admin/Manager of that user's own
    company (ROOT is not implicitly cross-company here -- see the
    `/companies` routes for root's company-scoped views)."""
    repository = UserRepository(db)
    service = UserService(repository)

    if current_user.id == user_id:
        user = await service.get_user_by_id(user_id)
    else:
        is_admin_or_manager = current_user.role in [UserRole.ADMIN.value, UserRole.MANAGER.value]
        if not is_admin_or_manager:
            raise AuthorizationException(message="You are not authorized to view this user's details.")
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
    """Update profile details of a user. Role or status changes require Admin privileges."""
    is_admin = current_user.role == UserRole.ADMIN.value
    is_self = current_user.id == user_id

    # Enforce privileges
    if not is_admin and not is_self:
        raise AuthorizationException(message="You are not authorized to update this user's information.")

    # Restrict field updates for non-admins
    if not is_admin:
        if schema.role is not None or schema.is_active is not None or schema.clearance_level is not None:
            raise AuthorizationException(
                message="Only administrators can update role, account status, or clearance level."
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
    """Update password of current logged-in user after validation."""
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
    """Soft delete user account by setting is_deleted flag (Admin only, own company)."""
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
    """Permanently delete user record from database (Admin only, own company)."""
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
    """Delegate a permission to a company user (Admin/Manager only).

    Privilege non-escalation: the granter itself must be authorized for
    ``schema.action`` (checked with its own identity standing in for the
    resource's owner) before it may hand that action to someone else -- a
    manager who only holds a delegated ``document:delete`` grant cannot in
    turn grant ``draft:send``, since it was never granted that itself. Built
    -in ADMIN/MANAGER role rules already cover every action defined today
    (see ``app.core.authz.rules.BUILTIN_RULES``), so this check only starts
    actually restricting once a manager's own permissions are themselves
    grant-derived rather than role-derived.
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
    return SuccessResponse(data=PermissionGrantResponse.model_validate(grant).model_dump(mode="json"))


@router.get("/{user_id}/permissions", response_model=APIResponse[List[PermissionGrantResponse]])
async def list_permissions(
    user_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """List every non-revoked permission explicitly granted to a company user (Admin/Manager only)."""
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
    """Revoke a permission grant (Admin/Manager only, own company).

    The revoked row is kept, not deleted (see
    ``PermissionGrantModel.revoked_at``'s docstring) -- its own audit trail.
    """
    grant_repository = PermissionGrantRepository(db)
    revoked = await grant_repository.revoke(grant_id, current_user.company_id)
    if not revoked:
        raise NotFoundException(message="Yetki bulunamadı ya da zaten geri alınmış.")
    await authz.invalidate_company(current_user.company_id)
    return SuccessResponse(data=None)
