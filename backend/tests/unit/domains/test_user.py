import pytest
from unittest.mock import AsyncMock, MagicMock
from app.domains.users.service import UserService
from app.domains.users.schema.user_schema import UserCreate
from app.core.enums.user_role import UserRole
from app.api.exceptions.conflict import ConflictException

@pytest.mark.asyncio
async def test_register_user_success():
    repository = MagicMock()
    repository.get_by_username = AsyncMock(return_value=None)
    repository.get_by_email = AsyncMock(return_value=None)
    repository.create = AsyncMock(side_effect=lambda user: user)

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

@pytest.mark.asyncio
async def test_register_user_username_taken():
    repository = MagicMock()
    repository.get_by_username = AsyncMock(return_value=MagicMock())
    repository.get_by_email = AsyncMock(return_value=None)

    service = UserService(repository)
    schema = UserCreate(
        username="john_doe",
        email="john@example.com",
        password="securepassword",
        role=UserRole.EMPLOYEE
    )

    with pytest.raises(ConflictException) as exc:
        await service.register_user(schema)
    assert "kullanıcı adı zaten alınmış" in str(exc.value.message)

@pytest.mark.asyncio
async def test_register_user_email_taken():
    repository = MagicMock()
    repository.get_by_username = AsyncMock(return_value=None)
    repository.get_by_email = AsyncMock(return_value=MagicMock())

    service = UserService(repository)
    schema = UserCreate(
        username="john_doe",
        email="john@example.com",
        password="securepassword",
        role=UserRole.EMPLOYEE
    )

    with pytest.raises(ConflictException) as exc:
        await service.register_user(schema)
    assert "e-posta adresi zaten kullanımda" in str(exc.value.message)
