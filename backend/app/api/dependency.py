from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums.user_role import UserRole
from app.core.security import decode_token
from app.infrastructure.database.session import get_db
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.domains.users.service import UserService
from app.api.exceptions.authentication import AuthenticationException
from app.api.exceptions.authorization import AuthorizationException

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> UserModel:
    """Dependency to retrieve and authenticate the currently logged-in user from the JWT access token."""
    if not token:
        raise AuthenticationException(message="Kimlik doğrulama token'ı eksik.")

    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationException(message="Geçersiz token kimliği.")

    user_repository = UserRepository(db)
    user_service = UserService(user_repository)
    
    try:
        user = await user_service.get_user_by_id(user_id)
        if not user.is_active:
            raise AuthenticationException(message="Kullanıcı hesabı aktif değil.")
        return user
    except Exception as exc:
        raise AuthenticationException(message="Kullanıcı bulunamadı.") from exc

def require_roles(*allowed_roles: UserRole):
    """Dependency generator to enforce role-based access control (RBAC) on endpoints."""
    def role_dependency(current_user: UserModel = Depends(get_current_user)) -> UserModel:
        if current_user.role not in [role.value for role in allowed_roles]:
            raise AuthorizationException(message="Bu işlem için yetkiniz bulunmamaktadır.")
        return current_user
    return role_dependency
