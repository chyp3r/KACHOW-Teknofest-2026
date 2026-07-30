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
