from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.model.permission_grant_model import PermissionGrantModel
from app.core.authz.repository import PermissionGrantRepository
from app.core.enums.user_role import UserRole


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def repo(mock_session):
    return PermissionGrantRepository(mock_session)


def _row(**overrides) -> PermissionGrantModel:
    fields = dict(
        id="grant-1",
        company_id="company-1",
        subject_type="user",
        subject_id="u-1",
        action="document:delete",
        resource_type="document",
        resource_selector={"any": True},
        conditions=[],
        effect="permit",
        priority=0,
        valid_from=None,
        valid_until=None,
        granted_by="admin-1",
        revoked_at=None,
        reason=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return PermissionGrantModel(**fields)


async def test_list_active_for_subject_converts_rows_to_grant_views(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [_row()]
    mock_session.execute.return_value = mock_result

    grants = await repo.list_active_for_subject("company-1", UserRole.EMPLOYEE, "u-1", "document:delete")

    assert len(grants) == 1
    assert grants[0].id == "grant-1"
    assert grants[0].effect == "permit"
    assert grants[0].time_boxed is False


async def test_list_active_for_subject_marks_time_boxed_grants(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        _row(valid_until=datetime.now(timezone.utc))
    ]
    mock_session.execute.return_value = mock_result

    grants = await repo.list_active_for_subject("company-1", UserRole.EMPLOYEE, "u-1", "document:delete")

    assert grants[0].time_boxed is True


async def test_create_assigns_an_id_when_missing(repo, mock_session):
    grant = _row(id="")
    grant.id = None
    created = await repo.create(grant)

    assert created.id
    mock_session.add.assert_called_once_with(grant)
    mock_session.flush.assert_awaited_once()


async def test_revoke_sets_revoked_at(repo, mock_session):
    row = _row(revoked_at=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row
    mock_session.execute.return_value = mock_result

    revoked = await repo.revoke("grant-1", "company-1")

    assert revoked is True
    assert row.revoked_at is not None


async def test_revoke_is_false_when_already_revoked(repo, mock_session):
    row = _row(revoked_at=datetime.now(timezone.utc))
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row
    mock_session.execute.return_value = mock_result

    revoked = await repo.revoke("grant-1", "company-1")

    assert revoked is False


async def test_revoke_is_false_when_grant_not_found(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    revoked = await repo.revoke("missing", "company-1")

    assert revoked is False
