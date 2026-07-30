import pytest
from unittest.mock import AsyncMock, MagicMock
from app.domains.users.service import UserService
from app.domains.users.schema.user_schema import UserCreate
from app.domains.users.schema.invited_email import InvitedEmailCreate
from app.core.enums.user_role import UserRole
from app.api.exceptions.conflict import ConflictException
from app.api.exceptions.authorization import AuthorizationException

@pytest.mark.asyncio
async def test_invite_email_success():
    repository = MagicMock()
    repository.get_by_email = AsyncMock(return_value=None)
    repository.get_invite_by_email = AsyncMock(return_value=None)
    repository.create_invite = AsyncMock(side_effect=lambda invite: invite)

    service = UserService(repository)
    schema = InvitedEmailCreate(email="new_employee@company.com", role=UserRole.EMPLOYEE)

    invite = await service.invite_user_email(schema)
    assert invite.email == "new_employee@company.com"
    assert invite.role == "employee"
    assert invite.is_used is False
    repository.create_invite.assert_called_once()

@pytest.mark.asyncio
async def test_invite_email_already_registered():
    repository = MagicMock()
    repository.get_by_email = AsyncMock(return_value=MagicMock())

    service = UserService(repository)
    schema = InvitedEmailCreate(email="existing@company.com", role=UserRole.EMPLOYEE)

    with pytest.raises(ConflictException) as exc:
        await service.invite_user_email(schema)
    assert "zaten bir kullanıcı kayıtlı" in str(exc.value.message)

@pytest.mark.asyncio
async def test_invite_email_already_invited():
    repository = MagicMock()
    repository.get_by_email = AsyncMock(return_value=None)
    repository.get_invite_by_email = AsyncMock(return_value=MagicMock())

    service = UserService(repository)
    schema = InvitedEmailCreate(email="invited@company.com", role=UserRole.EMPLOYEE)

    with pytest.raises(ConflictException) as exc:
        await service.invite_user_email(schema)
    assert "zaten davet edilmiş" in str(exc.value.message)

@pytest.mark.asyncio
async def test_register_without_invite_raises_forbidden():
    repository = MagicMock()
    repository.get_by_username = AsyncMock(return_value=None)
    repository.get_by_email = AsyncMock(return_value=None)
    repository.get_invite_by_email = AsyncMock(return_value=None)

    service = UserService(repository)
    schema = UserCreate(
        username="uninvited_user",
        email="not_invited@company.com",
        password="securepassword",
        role=UserRole.ADMIN
    )

    with pytest.raises(AuthorizationException) as exc:
        await service.register_user(schema)
    assert "davet edilmemiş" in str(exc.value.message)

@pytest.mark.asyncio
async def test_register_with_invite_success():
    mock_invite = MagicMock()
    mock_invite.email = "invited@company.com"
    mock_invite.role = "manager"
    mock_invite.is_used = False

    repository = MagicMock()
    repository.get_by_username = AsyncMock(return_value=None)
    repository.get_by_email = AsyncMock(return_value=None)
    repository.get_invite_by_email = AsyncMock(return_value=mock_invite)
    repository.create = AsyncMock(side_effect=lambda user: user)
    repository.mark_invite_used = AsyncMock(return_value=True)

    service = UserService(repository)
    schema = UserCreate(
        username="invited_user",
        email="invited@company.com",
        password="securepassword",
        role=UserRole.EMPLOYEE
    )

    user = await service.register_user(schema)
    assert user.username == "invited_user"
    assert user.email == "invited@company.com"
    assert user.role == "manager"
    assert user.is_active is True
    repository.mark_invite_used.assert_called_once_with("invited@company.com")
