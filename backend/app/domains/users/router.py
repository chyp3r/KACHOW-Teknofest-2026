from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_db
from app.api.responses import APIResponse, SuccessResponse
from app.domains.users.schema.user_schema import UserCreate, UserUpdate, PasswordChangeRequest, UserResponse
from app.domains.users.schema.invited_email import InvitedEmailCreate, InvitedEmailResponse
from app.domains.users.repository import UserRepository
from app.domains.users.service import UserService
from app.domains.users.model.user_model import UserModel
from app.api.dependency import get_current_user, require_roles
from app.core.enums.user_role import UserRole
from app.api.exceptions.authorization import AuthorizationException

router = APIRouter(prefix="/users", tags=["users"])

@router.post("", response_model=APIResponse[UserResponse])
async def register(schema: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user account in the system, validating the email invitation whitelist."""
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
    """Invite/whitelist an email address with a predefined role for registration (Admin/Manager only)."""
    repository = UserRepository(db)
    service = UserService(repository)
    invite = await service.invite_user_email(schema)
    response_data = InvitedEmailResponse.model_validate(invite)
    return SuccessResponse(data=response_data, message="Email address successfully invited.")

@router.get("", response_model=APIResponse[List[UserResponse]])
async def list_users(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    role: Optional[UserRole] = Query(default=None),
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve multiple users with pagination and role filters (Admin/Manager only)."""
    repository = UserRepository(db)
    service = UserService(repository)
    role_str = role.value if role else None
    users = await service.get_users(skip=skip, limit=limit, role=role_str)
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
    """Retrieve details of a specific user. Authenticated user can only retrieve themselves, unless they are Admin/Manager."""
    is_admin_or_manager = current_user.role in [UserRole.ADMIN.value, UserRole.MANAGER.value]
    if not is_admin_or_manager and current_user.id != user_id:
        raise AuthorizationException(message="You are not authorized to view this user's details.")

    repository = UserRepository(db)
    service = UserService(repository)
    user = await service.get_user_by_id(user_id)
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
        if schema.role is not None or schema.is_active is not None:
            raise AuthorizationException(message="Only administrators can update role or account status.")

    repository = UserRepository(db)
    service = UserService(repository)
    updated_user = await service.update_user(user_id, schema)
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
    """Soft delete user account by setting is_deleted flag (Admin only)."""
    repository = UserRepository(db)
    service = UserService(repository)
    await service.soft_delete_user(user_id)
    return SuccessResponse(data=None)

@router.delete("/{user_id}/hard", response_model=APIResponse[None])
async def hard_delete(
    user_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db)
):
    """Permanently delete user record from database (Admin only)."""
    repository = UserRepository(db)
    service = UserService(repository)
    await service.hard_delete_user(user_id)
    return SuccessResponse(data=None)
