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
async def test_refresh_token_blacklisted():
    refresh_tok = create_refresh_token("user-id")
    
    mock_cache = MagicMock()
    mock_cache.exists = AsyncMock(return_value=True)
    
    schema = RefreshRequest(refresh_token=refresh_tok)
    with patch("app.domains.auth.router.get_cache", return_value=mock_cache):
        with pytest.raises(AuthenticationException) as exc:
            await refresh_endpoint(schema=schema, request=MagicMock(), db=MagicMock())
        assert "terminated" in str(exc.value.message)

@pytest.mark.asyncio
async def test_refresh_token_success():
    hashed = hash_password("securepassword")
    
    mock_user = MagicMock()
    mock_user.id = "user-uuid"
    mock_user.username = "john_doe"
    mock_user.hashed_password = hashed
    mock_user.role = "employee"
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
            await get_current_user(token=token, db=MagicMock())
        assert "Session has been terminated" in str(exc.value.message)
