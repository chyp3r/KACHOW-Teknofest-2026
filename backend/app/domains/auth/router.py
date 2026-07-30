from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_db
from app.api.responses import APIResponse, SuccessResponse
from app.domains.auth.schema.auth_schema import LoginRequest, TokenResponse
from app.domains.users.repository import UserRepository
from app.domains.auth.service import AuthService
from app.api.dependency import oauth2_scheme
from app.infrastructure.cache import get_cache
from app.core.security import decode_token
import time

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=APIResponse[TokenResponse])
async def login(schema: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user credentials and issue access tokens."""
    user_repository = UserRepository(db)
    service = AuthService(user_repository)
    token_response = await service.authenticate_user(schema)
    return SuccessResponse(data=token_response)

@router.post("/logout", response_model=APIResponse[None])
async def logout(token: str = Depends(oauth2_scheme)):
    """Logout the current user and blacklist their JWT token in Redis Cache."""
    if token:
        try:
            payload = decode_token(token)
            exp = payload.get("exp")
            if exp:
                remaining = int(exp - time.time())
                if remaining > 0:
                    cache = get_cache()
                    await cache.set(f"token_blacklist:{token}", "1", expire_seconds=remaining)
        except Exception:
            # Ignore if token is already expired or invalid
            pass
    return SuccessResponse(data=None)
