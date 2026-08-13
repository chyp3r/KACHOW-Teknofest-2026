import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.engine import Result

from app.domains.users.repository import UserRepository
from app.domains.users.model.user_model import UserModel
from app.domains.users.model.invited_email import InvitedEmailModel

@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)

@pytest.fixture
def repo(mock_session):
    return UserRepository(mock_session)

@pytest.mark.asyncio
async def test_get_by_id(repo, mock_session):
    mock_result = MagicMock()
    mock_user = UserModel(id="user-123", username="testuser", email="test@example.com", role="employee", is_active=True, is_deleted=False, hashed_password="pw")
    mock_result.scalar_one_or_none.return_value = mock_user
    mock_session.execute.return_value = mock_result
    
    user = await repo.get_by_id("user-123")
    assert user is not None
    assert user.id == "user-123"
    assert user.username == "testuser"
    mock_session.execute.assert_called_once()

@pytest.mark.asyncio
async def test_get_by_email(repo, mock_session):
    mock_result = MagicMock()
    mock_user = UserModel(id="user-123", username="testuser", email="test@example.com", role="employee", is_active=True, is_deleted=False, hashed_password="pw")
    mock_result.scalar_one_or_none.return_value = mock_user
    mock_session.execute.return_value = mock_result
    
    user = await repo.get_by_email("test@example.com")
    assert user is not None
    assert user.email == "test@example.com"
    mock_session.execute.assert_called_once()

@pytest.mark.asyncio
async def test_get_by_username(repo, mock_session):
    mock_result = MagicMock()
    mock_user = UserModel(id="user-123", username="testuser", email="test@example.com", role="employee", is_active=True, is_deleted=False, hashed_password="pw")
    mock_result.scalar_one_or_none.return_value = mock_user
    mock_session.execute.return_value = mock_result
    
    user = await repo.get_by_username("testuser")
    assert user is not None
    assert user.username == "testuser"
    mock_session.execute.assert_called_once()

@pytest.mark.asyncio
async def test_create(repo, mock_session):
    new_user = UserModel(id="user-123", username="testuser", email="test@example.com", role="employee", is_active=True, is_deleted=False, hashed_password="pw")
    
    result = await repo.create(new_user)
    assert result == new_user
    mock_session.add.assert_called_once_with(new_user)
    mock_session.flush.assert_called_once()

@pytest.mark.asyncio
async def test_update(repo, mock_session):
    user = UserModel(id="user-123", username="testuser", email="test@example.com", role="employee", is_active=True, is_deleted=False, hashed_password="pw")
    
    result = await repo.update(user, {"username": "newname"})
    assert result.username == "newname"
    mock_session.flush.assert_called_once()

@pytest.mark.asyncio
async def test_soft_delete(repo, mock_session):
    mock_result = MagicMock()
    user = UserModel(id="user-123", username="testuser", email="test@example.com", role="employee", is_active=True, is_deleted=False, hashed_password="pw")
    mock_result.scalar_one_or_none.return_value = user
    mock_session.execute.return_value = mock_result
    
    result = await repo.soft_delete("user-123", "company-1")
    assert result.is_deleted is True
    assert result.is_active is False
    mock_session.flush.assert_called_once()

@pytest.mark.asyncio
async def test_hard_delete(repo, mock_session):
    mock_result = MagicMock()
    mock_result.rowcount = 1
    mock_session.execute.return_value = mock_result

    result = await repo.hard_delete("user-123", "company-1")
    assert result is True
    mock_session.flush.assert_called_once()

@pytest.mark.asyncio
async def test_get_multi_no_filters(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        UserModel(id="1", username="test1", email="t1@example.com", role="employee", is_active=True, is_deleted=False, hashed_password="pw"),
        UserModel(id="2", username="test2", email="t2@example.com", role="employee", is_active=True, is_deleted=False, hashed_password="pw")
    ]
    mock_session.execute.return_value = mock_result

    users = await repo.get_multi("company-1", skip=0, limit=10)
    assert len(users) == 2
    mock_session.execute.assert_called_once()

@pytest.mark.asyncio
async def test_get_multi_with_filters(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        UserModel(id="1", username="test1", email="t1@example.com", role="employee", is_active=True, is_deleted=False, hashed_password="pw")
    ]
    mock_session.execute.return_value = mock_result

    users = await repo.get_multi("company-1", skip=0, limit=10, role="admin")
    assert len(users) == 1
    mock_session.execute.assert_called_once()

@pytest.mark.asyncio
async def test_get_invite_by_email(repo, mock_session):
    mock_result = MagicMock()
    mock_invite = InvitedEmailModel(email="test@example.com", role="employee", is_used=False)
    mock_result.scalar_one_or_none.return_value = mock_invite
    mock_session.execute.return_value = mock_result
    
    invite = await repo.get_invite_by_email("test@example.com")
    assert invite is not None
    assert invite.email == "test@example.com"
    mock_session.execute.assert_called_once()

@pytest.mark.asyncio
async def test_create_invite(repo, mock_session):
    new_invite = InvitedEmailModel(email="test@example.com", role="employee", is_used=False)
    
    result = await repo.create_invite(new_invite)
    assert result == new_invite
    mock_session.add.assert_called_once_with(new_invite)
    mock_session.flush.assert_called_once()

@pytest.mark.asyncio
async def test_mark_invite_used(repo, mock_session):
    mock_result = MagicMock()
    mock_invite = InvitedEmailModel(email="test@example.com", role="employee", is_used=False)
    mock_result.scalar_one_or_none.return_value = mock_invite
    mock_session.execute.return_value = mock_result
    
    result = await repo.mark_invite_used("test@example.com")
    assert result is True
    assert mock_invite.is_used is True
    mock_session.flush.assert_called_once()
