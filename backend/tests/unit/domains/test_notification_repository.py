from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.notifications.model.notification_model import NotificationModel
from app.domains.notifications.repository import NotificationRepository


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def repo(mock_session):
    return NotificationRepository(mock_session)


def _notification(**overrides) -> NotificationModel:
    fields = dict(
        id="notif-1", company_id="company-1", user_id="user-1", type="draft_shared",
        title="Başlık", body="Gövde", resource_type="draft_share", resource_id="share-1",
        read_at=None,
    )
    fields.update(overrides)
    return NotificationModel(**fields)


async def test_create_adds_and_flushes(repo, mock_session):
    notification = _notification()

    result = await repo.create(notification)

    assert result is notification
    mock_session.add.assert_called_once_with(notification)
    mock_session.flush.assert_awaited_once()


async def test_list_for_user_returns_rows(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [_notification()]
    mock_session.execute.return_value = mock_result

    result = await repo.list_for_user("company-1", "user-1")

    assert len(result) == 1


async def test_mark_read_sets_timestamp_once(repo, mock_session):
    notification = _notification(read_at=None)

    result = await repo.mark_read(notification)

    assert result.read_at is not None
    mock_session.flush.assert_awaited_once()


async def test_mark_read_is_idempotent(repo, mock_session):
    from datetime import datetime, timezone

    already = datetime.now(timezone.utc)
    notification = _notification(read_at=already)

    result = await repo.mark_read(notification)

    assert result.read_at is already
    mock_session.flush.assert_not_awaited()


async def test_mark_all_read_returns_rowcount(repo, mock_session):
    mock_result = MagicMock()
    mock_result.rowcount = 4
    mock_session.execute.return_value = mock_result

    assert await repo.mark_all_read("company-1", "user-1") == 4
