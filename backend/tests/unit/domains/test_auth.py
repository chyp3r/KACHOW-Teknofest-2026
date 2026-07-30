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
    assert "Hatalı kullanıcı adı" in str(exc.value.message)

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
    assert "aktif değil" in str(exc.value.message)

from unittest.mock import patch
from app.domains.auth.router import logout
from app.core.security import create_access_token

@pytest.mark.asyncio
async def test_logout_endpoint():
    token = create_access_token("user-id", extra_claims={"role": "employee"})
    
    mock_cache = MagicMock()
    mock_cache.set = AsyncMock(return_value=True)
    
    with patch("app.domains.auth.router.get_cache", return_value=mock_cache):
        response = await logout(token=token)
        # response is JSONResponse from SuccessResponse
        assert response.status_code == 200
        mock_cache.set.assert_called_once()
        assert "token_blacklist" in mock_cache.set.call_args[0][0]

from app.api.dependency import get_current_user

@pytest.mark.asyncio
async def test_get_current_user_blacklisted():
    token = create_access_token("user-id", extra_claims={"role": "employee"})
    
    mock_cache = MagicMock()
    mock_cache.exists = AsyncMock(return_value=True)
    
    with patch("app.api.dependency.get_cache", return_value=mock_cache):
        with pytest.raises(AuthenticationException) as exc:
            await get_current_user(token=token, db=MagicMock())
        assert "Oturum sonlandırılmış" in str(exc.value.message)
