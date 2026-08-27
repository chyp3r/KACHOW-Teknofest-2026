import pytest
from unittest.mock import AsyncMock, MagicMock
from app.domains.auth.service import AuthService
from app.domains.auth.schema.auth_schema import LoginRequest
from app.core.security import hash_password
from app.api.exceptions.authentication import AuthenticationException

@pytest.mark.asyncio
async def test_authenticate_user_success():
    hashed = hash_password("securepassword")
    
    mock_user = MagicMock()
    mock_user.id = "user-uuid"
    mock_user.username = "john_doe"
    mock_user.hashed_password = hashed
    mock_user.role = "employee"
    mock_user.company_id = "company-1"
    mock_user.is_active = True

    repository = MagicMock()
    repository.get_by_username = AsyncMock(return_value=mock_user)

    service = AuthService(repository)
    schema = LoginRequest(username="john_doe", password="securepassword")

    response = await service.authenticate_user(schema)
    assert response.access_token is not None
    assert response.refresh_token is not None
    assert response.token_type == "bearer"

@pytest.mark.asyncio
async def test_authenticate_user_invalid_password():
    hashed = hash_password("securepassword")
    
    mock_user = MagicMock()
    mock_user.hashed_password = hashed
    mock_user.is_active = True

    repository = MagicMock()
    repository.get_by_username = AsyncMock(return_value=mock_user)

    service = AuthService(repository)
    schema = LoginRequest(username="john_doe", password="wrongpassword")

    with pytest.raises(AuthenticationException) as exc:
        await service.authenticate_user(schema)
    assert "Invalid username" in str(exc.value.message)

@pytest.mark.asyncio
async def test_authenticate_user_inactive():
    hashed = hash_password("securepassword")
    
    mock_user = MagicMock()
    mock_user.hashed_password = hashed
    mock_user.is_active = False

    repository = MagicMock()
    repository.get_by_username = AsyncMock(return_value=mock_user)

    service = AuthService(repository)
    schema = LoginRequest(username="john_doe", password="securepassword")

    with pytest.raises(AuthenticationException) as exc:
        await service.authenticate_user(schema)
    assert "not active" in str(exc.value.message)

from unittest.mock import patch
from app.domains.auth.router import logout, refresh as refresh_endpoint
from app.domains.auth.schema.auth_schema import RefreshRequest
from app.core.security import create_access_token, create_refresh_token

@pytest.mark.asyncio
async def test_logout_endpoint():
    token = create_access_token("user-id", extra_claims={"role": "employee"})
    refresh_tok = create_refresh_token("user-id")
    
    mock_cache = MagicMock()
    mock_cache.set = AsyncMock(return_value=True)
    
    schema = RefreshRequest(refresh_token=refresh_tok)
    with patch("app.domains.auth.router.get_cache", return_value=mock_cache):
        response = await logout(schema=schema, token=token)
        assert response.status_code == 200
        # Both access and refresh tokens should be blacklisted
        assert mock_cache.set.call_count == 2
        keys = [call[0][0] for call in mock_cache.set.call_args_list]
        assert all("token_blacklist" in k for k in keys)

@pytest.mark.asyncio
async def test_logout_raises_when_a_live_token_cannot_be_blacklisted():
    """RedisCache.set() never raises -- it logs internally and returns False on
    failure (a Redis outage, say) -- so that return value was the only signal a
    blacklist attempt failed, and it used to be discarded entirely. Logout
    returned 200 whether or not the token was actually revoked: a user logging
    out on a shared machine during a Redis blip believed the session was dead
    when it remained fully valid until natural expiry, with nothing telling
    them otherwise."""
    from app.api.exceptions.base import BaseAppException

    token = create_access_token("user-id", extra_claims={"role": "employee"})
    refresh_tok = create_refresh_token("user-id")

    mock_cache = MagicMock()
    mock_cache.set = AsyncMock(return_value=False)  # the outage

    schema = RefreshRequest(refresh_token=refresh_tok)
    with patch("app.domains.auth.router.get_cache", return_value=mock_cache):
        with pytest.raises(BaseAppException) as exc:
            await logout(schema=schema, token=token)
        assert exc.value.status_code == 500
        assert set(exc.value.details["unrevoked_tokens"]) == {"access", "refresh"}


@pytest.mark.asyncio
async def test_logout_still_succeeds_when_only_the_access_token_write_fails():
    """Partial failure is still a failure -- one live, unrevoked token is
    exactly the gap this exists to close, even if its sibling succeeded."""
    from app.api.exceptions.base import BaseAppException

    token = create_access_token("user-id", extra_claims={"role": "employee"})
    refresh_tok = create_refresh_token("user-id")

    mock_cache = MagicMock()
    mock_cache.set = AsyncMock(side_effect=[False, True])  # access fails, refresh ok

    schema = RefreshRequest(refresh_token=refresh_tok)
    with patch("app.domains.auth.router.get_cache", return_value=mock_cache):
        with pytest.raises(BaseAppException) as exc:
            await logout(schema=schema, token=token)
        assert exc.value.details["unrevoked_tokens"] == ["access"]


@pytest.mark.asyncio
async def test_logout_does_not_treat_an_already_expired_token_as_a_failure():
    """A token with no remaining lifetime has nothing to revoke -- that must
    not count as a blacklist failure, or logout would raise on every already-
    expired token a client happens to still be holding."""
    import time as time_module

    from app.core.security import decode_token as real_decode_token

    token = create_access_token("user-id", extra_claims={"role": "employee"})
    refresh_tok = create_refresh_token("user-id")

    mock_cache = MagicMock()
    mock_cache.set = AsyncMock(return_value=True)

    # Simulate an access token whose exp has already passed by patching what
    # decode_token returns for it, rather than waiting for a real expiry.
    expired_payload = real_decode_token(token)
    expired_payload["exp"] = int(time_module.time()) - 10

    schema = RefreshRequest(refresh_token=refresh_tok)
    with patch("app.domains.auth.router.get_cache", return_value=mock_cache):
        with patch(
            "app.domains.auth.router.decode_token",
            side_effect=lambda t: expired_payload if t == token else real_decode_token(t),
        ):
            response = await logout(schema=schema, token=token)

    assert response.status_code == 200
    # Only the still-live refresh token should have been written.
    assert mock_cache.set.call_count == 1
    assert "token_blacklist" in mock_cache.set.call_args_list[0][0][0]


@pytest.mark.asyncio
async def test_refresh_token_blacklisted():
    refresh_tok = create_refresh_token("user-id")
    
    mock_cache = MagicMock()
    mock_cache.exists = AsyncMock(return_value=True)
    
    schema = RefreshRequest(refresh_token=refresh_tok)
    with patch("app.domains.auth.router.get_cache", return_value=mock_cache):
        with pytest.raises(AuthenticationException) as exc:
            await refresh_endpoint(schema=schema, request=MagicMock(), db=MagicMock())
        assert "sonlandırıldı" in str(exc.value.message)

@pytest.mark.asyncio
async def test_refresh_token_success():
    hashed = hash_password("securepassword")
    
    mock_user = MagicMock()
    mock_user.id = "user-uuid"
    mock_user.username = "john_doe"
    mock_user.hashed_password = hashed
    mock_user.role = "employee"
    mock_user.company_id = "company-1"
    mock_user.is_active = True

    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=mock_user)

    service = AuthService(repository)
    refresh_tok = create_refresh_token("user-uuid")

    response = await service.refresh_access_token(refresh_tok)
    assert response.access_token is not None
    assert response.refresh_token is not None
    assert response.token_type == "bearer"

from app.api.dependency import get_current_user

@pytest.mark.asyncio
async def test_get_current_user_blacklisted():
    token = create_access_token("user-id", extra_claims={"role": "employee"})
    
    mock_cache = MagicMock()
    mock_cache.exists = AsyncMock(return_value=True)
    
    with patch("app.api.dependency.get_cache", return_value=mock_cache):
        with pytest.raises(AuthenticationException) as exc:
            await get_current_user(token=token)
        assert "sonlandırıldı" in str(exc.value.message)
