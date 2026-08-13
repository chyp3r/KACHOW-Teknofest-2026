import logging
from typing import Optional

from fastapi import APIRouter, Depends, Body, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_owner_db
from app.api.responses import APIResponse, SuccessResponse
from app.domains.auth.schema.auth_schema import LoginRequest, TokenResponse, RefreshRequest
from app.domains.users.repository import UserRepository
from app.domains.auth.service import AuthService
from app.api.dependency import oauth2_scheme
from app.infrastructure.cache import get_cache
from app.core.security import decode_token, REFRESH_TOKEN_EXPIRE_DAYS
from app.api.exceptions.authentication import AuthenticationException
from app.api.exceptions.base import BaseAppException
from app.api.rate_limit import rate_limit
import time

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=APIResponse[TokenResponse])
async def login(
    schema: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_owner_db),
    _: None = Depends(rate_limit(max_requests=5, window_seconds=60, key_prefix="auth:login")),
):
    """Authenticate user credentials and issue access + refresh tokens.

    Rate limit: max 5 requests per minute per IP.

    Uses ``get_owner_db``, not ``get_db``: ``username``/``email`` are unique
    system-wide, not per company, so looking a caller up by either one is
    inherently cross-tenant -- there is no company to scope a row-level
    -security policy by until this call resolves who they are (see
    ``get_owner_db``'s own docstring).
    """
    user_repository = UserRepository(db)
    service = AuthService(user_repository)
    token_response = await service.authenticate_user(schema)
    return SuccessResponse(data=token_response)

@router.post("/refresh", response_model=APIResponse[TokenResponse])
async def refresh(
    schema: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_owner_db),
    _: None = Depends(rate_limit(max_requests=20, window_seconds=60, key_prefix="auth:refresh")),
):
    """Exchange a valid refresh token for a new access + refresh token pair.

    Rate limit: max 20 requests per minute per IP.
    The refresh token is validated against:
    - JWT signature and expiry
    - Token type (must be 'refresh', not 'access')
    - Redis blacklist (invalidated on logout)
    - Active user status

    Uses ``get_owner_db``, not ``get_db``: a refresh token carries no
    ``company_id`` claim (only an access token does -- see
    ``AuthService.refresh_access_token``), so there is no tenant context
    available yet to scope a row-level-security policy by (same reasoning
    as ``login`` above).
    """
    cache = get_cache()
    if await cache.exists(f"token_blacklist:{schema.refresh_token}"):
        raise AuthenticationException(message="This session has been terminated. Please log in again.")

    user_repository = UserRepository(db)
    service = AuthService(user_repository)
    token_response = await service.refresh_access_token(schema.refresh_token)
    return SuccessResponse(data=token_response)

async def _blacklist(cache, token: str, now: float) -> Optional[bool]:
    """Blacklist one token for the remainder of its natural lifetime.

    Args:
        cache: The Redis cache client.
        token: The raw JWT to blacklist.
        now: Current epoch time, shared across both tokens in one logout call
            so they are judged against the same instant.

    Returns:
        True if the token was live and successfully blacklisted, False if it
        was live but the write failed, None if the token could not be decoded
        or had already expired -- there was nothing to revoke, which is not a
        failure. Only a `False` return should ever surface to the caller.
    """
    try:
        payload = decode_token(token)
    except Exception:
        # A malformed or already-expired token carries no live session to
        # revoke -- nothing failed here, there was simply nothing to do.
        return None
    exp = payload.get("exp")
    if not exp:
        return None
    remaining = int(exp - now)
    if remaining <= 0:
        return None
    # cache.set() never raises (see RedisCache.set); it logs internally and
    # returns False on failure. That return value is the only signal a
    # blacklist attempt failed, and it used to be discarded entirely --
    # logout returned 200 whether or not the token was actually revoked, so
    # a user who logged out on a shared machine during a Redis blip had no
    # way to know the token was still live.
    return await cache.set(f"token_blacklist:{token}", "1", expire_seconds=remaining)


@router.post("/logout", response_model=APIResponse[None])
async def logout(schema: RefreshRequest = Body(default=None), token: str = Depends(oauth2_scheme)):
    """Logout the current user by blacklisting both access and refresh tokens in Redis.

    Raises:
        BaseAppException: 500, if a token that was still live could not be
            blacklisted -- the caller must not be told logout succeeded when
            the token remains usable.
    """
    cache = get_cache()
    now = time.time()

    results = []
    if token:
        results.append(("access", await _blacklist(cache, token, now)))
    if schema and schema.refresh_token:
        results.append(("refresh", await _blacklist(cache, schema.refresh_token, now)))

    failed = [kind for kind, ok in results if ok is False]
    if failed:
        logger.error("Logout could not revoke %s token(s); they remain valid until natural expiry.", failed)
        raise BaseAppException(
            message="Logout could not fully revoke your session. Please try again.",
            error_code="LOGOUT_REVOCATION_FAILED",
            status_code=500,
            details={"unrevoked_tokens": failed},
        )

    return SuccessResponse(data=None)
