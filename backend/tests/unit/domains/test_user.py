import pytest
from unittest.mock import AsyncMock, MagicMock
from app.domains.users.service import UserService
from app.domains.users.schema.user_schema import UserCreate, UserUpdate, PasswordChangeRequest
from app.core.enums.user_role import UserRole
from app.api.exceptions.conflict import ConflictException
from app.api.exceptions.not_found import NotFoundException
from app.api.exceptions.authentication import AuthenticationException
from app.core.security import hash_password

@pytest.mark.asyncio
async def test_register_user_success():
    mock_invite = MagicMock()
    mock_invite.email = "john@example.com"
    mock_invite.role = "employee"

    repository = MagicMock()
    repository.get_by_username = AsyncMock(return_value=None)
    repository.get_by_email = AsyncMock(return_value=None)
    repository.get_invite_by_email = AsyncMock(return_value=mock_invite)
    repository.create = AsyncMock(side_effect=lambda user: user)
    repository.mark_invite_used = AsyncMock(return_value=True)

    service = UserService(repository)
    schema = UserCreate(
        username="john_doe",
        email="john@example.com",
        password="securepassword",
        role=UserRole.EMPLOYEE
    )

    user = await service.register_user(schema)
    assert user.username == "john_doe"
    assert user.email == "john@example.com"
    assert user.role == "employee"
    assert user.hashed_password is not None
    assert user.is_active is True
    assert user.is_deleted is False

@pytest.mark.asyncio
async def test_get_users_multi():
    repository = MagicMock()
    mock_users = [MagicMock(), MagicMock()]
    repository.get_multi = AsyncMock(return_value=mock_users)

    service = UserService(repository)
    result = await service.get_users("company-1", skip=0, limit=10, role="employee")
    assert len(result) == 2
    repository.get_multi.assert_called_once_with("company-1", skip=0, limit=10, role="employee")

@pytest.mark.asyncio
async def test_update_user_success():
    repository = MagicMock()
    mock_user = MagicMock()
    mock_user.email = "old@example.com"
    
    repository.get_by_id_in_company = AsyncMock(return_value=mock_user)
    repository.get_by_email = AsyncMock(return_value=None)
    repository.update = AsyncMock(return_value=mock_user)

    service = UserService(repository)
    schema = UserUpdate(email="new@example.com", role=UserRole.MANAGER, is_active=True)

    await service.update_user("user-id", schema, "company-1")
    
    repository.update.assert_called_once()
    call_args = repository.update.call_args[0][1]
    assert call_args["email"] == "new@example.com"
    assert call_args["role"] == "manager"
    assert call_args["is_active"] is True

@pytest.mark.asyncio
async def test_change_password_success():
    hashed = hash_password("old_password")
    
    repository = MagicMock()
    mock_user = MagicMock()
    mock_user.hashed_password = hashed
    
    repository.get_by_id = AsyncMock(return_value=mock_user)
    repository.update = AsyncMock()

    service = UserService(repository)
    schema = PasswordChangeRequest(current_password="old_password", new_password="new_password")
    
    await service.change_password("user-id", schema)
    repository.update.assert_called_once()

@pytest.mark.asyncio
async def test_change_password_invalid_current():
    hashed = hash_password("old_password")
    
    repository = MagicMock()
    mock_user = MagicMock()
    mock_user.hashed_password = hashed
    
    repository.get_by_id = AsyncMock(return_value=mock_user)

    service = UserService(repository)
    schema = PasswordChangeRequest(current_password="wrong_password", new_password="new_password")
    
    with pytest.raises(AuthenticationException):
        await service.change_password("user-id", schema)

@pytest.mark.asyncio
async def test_soft_delete_success():
    repository = MagicMock()
    repository.soft_delete = AsyncMock(return_value=MagicMock())

    service = UserService(repository)
    await service.soft_delete_user("user-id", "company-1")
    repository.soft_delete.assert_called_once_with("user-id", "company-1")

@pytest.mark.asyncio
async def test_hard_delete_success():
    repository = MagicMock()
    repository.hard_delete = AsyncMock(return_value=True)

    service = UserService(repository)
    await service.hard_delete_user("user-id", "company-1")
    repository.hard_delete.assert_called_once_with("user-id", "company-1")

@pytest.mark.asyncio
async def test_delete_user_not_found():
    repository = MagicMock()
    repository.soft_delete = AsyncMock(return_value=None)
    repository.hard_delete = AsyncMock(return_value=False)

    service = UserService(repository)
    with pytest.raises(NotFoundException):
        await service.soft_delete_user("user-id", "company-1")

    with pytest.raises(NotFoundException):
        await service.hard_delete_user("user-id", "company-1")
