from fastapi import APIRouter, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_db
from app.api.responses import APIResponse, SuccessResponse
from app.domains.auth.schema.auth_schema import LoginRequest, TokenResponse, RefreshRequest
from app.domains.users.repository import UserRepository
from app.domains.auth.service import AuthService
from app.api.dependency import oauth2_scheme
from app.infrastructure.cache import get_cache
from app.core.security import decode_token, REFRESH_TOKEN_EXPIRE_DAYS
from app.api.exceptions.authentication import AuthenticationException
import time

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=APIResponse[TokenResponse])
async def login(schema: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user credentials and issue access + refresh tokens."""
    user_repository = UserRepository(db)
    service = AuthService(user_repository)
    token_response = await service.authenticate_user(schema)
    return SuccessResponse(data=token_response)

@router.post("/refresh", response_model=APIResponse[TokenResponse])
async def refresh(schema: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token for a new access + refresh token pair.
    
    The refresh token is validated against:
    - JWT signature and expiry
    - Token type (must be 'refresh', not 'access')
    - Redis blacklist (invalidated on logout)
    - Active user status
    """
    cache = get_cache()
    if await cache.exists(f"token_blacklist:{schema.refresh_token}"):
        raise AuthenticationException(message="Bu oturum sonlandırılmış. Lütfen tekrar giriş yapın.")

    user_repository = UserRepository(db)
    service = AuthService(user_repository)
    token_response = await service.refresh_access_token(schema.refresh_token)
    return SuccessResponse(data=token_response)

@router.post("/logout", response_model=APIResponse[None])
async def logout(schema: RefreshRequest = Body(default=None), token: str = Depends(oauth2_scheme)):
    """Logout the current user by blacklisting both access and refresh tokens in Redis."""
    cache = get_cache()
    now = time.time()

    # Blacklist access token
    if token:
        try:
            payload = decode_token(token)
            exp = payload.get("exp")
            if exp:
                remaining = int(exp - now)
                if remaining > 0:
                    await cache.set(f"token_blacklist:{token}", "1", expire_seconds=remaining)
        except Exception:
            pass

    # Blacklist refresh token
    if schema and schema.refresh_token:
        try:
            payload = decode_token(schema.refresh_token)
            exp = payload.get("exp")
            if exp:
                remaining = int(exp - now)
                if remaining > 0:
                    await cache.set(f"token_blacklist:{schema.refresh_token}", "1", expire_seconds=remaining)
        except Exception:
            pass

    return SuccessResponse(data=None)
