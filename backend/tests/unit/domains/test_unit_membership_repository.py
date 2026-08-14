from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.units.model.unit_membership_model import UnitMembershipModel
from app.domains.units.repository import UnitMembershipRepository
from app.domains.users.model.user_model import UserModel


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def repo(mock_session):
    return UnitMembershipRepository(mock_session)


def _membership(**overrides) -> UnitMembershipModel:
    fields = dict(
        id="m-1", company_id="company-1", unit_id="unit-1", user_id="user-1",
        is_primary=False, role_in_unit=None,
    )
    fields.update(overrides)
    return UnitMembershipModel(**fields)


def _user(**overrides) -> UserModel:
    fields = dict(
        id="user-1", company_id="company-1", username="u1", email="u1@example.com",
        role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False,
        hashed_password="x", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return UserModel(**fields)


async def test_get_returns_none_when_not_found(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    result = await repo.get("unit-1", "user-1", "company-1")

    assert result is None


async def test_list_for_unit_joins_user_identity(repo, mock_session):
    membership = _membership()
    user = _user()
    mock_result = MagicMock()
    mock_result.all.return_value = [(membership, user)]
    mock_session.execute.return_value = mock_result

    result = await repo.list_for_unit("unit-1", "company-1")

    assert result == [(membership, user)]


async def test_clear_primary_for_user_demotes_existing_primaries(repo, mock_session):
    primary = _membership(id="m-2", is_primary=True)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [primary]
    mock_session.execute.return_value = mock_result

    await repo.clear_primary_for_user("user-1", "company-1")

    assert primary.is_primary is False
    mock_session.flush.assert_awaited_once()


async def test_create_adds_and_flushes(repo, mock_session):
    membership = _membership()

    result = await repo.create(membership)

    assert result is membership
    mock_session.add.assert_called_once_with(membership)
    mock_session.flush.assert_awaited_once()


async def test_delete_returns_true_when_a_row_was_removed(repo, mock_session):
    mock_result = MagicMock()
    mock_result.rowcount = 1
    mock_session.execute.return_value = mock_result

    deleted = await repo.delete("unit-1", "user-1", "company-1")

    assert deleted is True


async def test_delete_returns_false_when_nothing_matched(repo, mock_session):
    mock_result = MagicMock()
    mock_result.rowcount = 0
    mock_session.execute.return_value = mock_result

    deleted = await repo.delete("unit-1", "user-1", "company-1")

    assert deleted is False
