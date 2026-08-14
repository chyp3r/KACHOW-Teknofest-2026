from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.domains.notifications.model.notification_model import NotificationModel
from app.domains.notifications.service import NotificationService, channel_for


def _notification(**overrides) -> NotificationModel:
    fields = dict(
        id="notif-1", company_id="company-1", user_id="user-1", type="draft_shared",
        title="Başlık", body="Gövde", resource_type="draft_share", resource_id="share-1",
        read_at=None,
    )
    fields.update(overrides)
    return NotificationModel(**fields)


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def cache():
    return AsyncMock()


@pytest.fixture
def service(repo, cache):
    return NotificationService(repo, cache=cache)


def test_channel_for_is_scoped_by_company_and_user():
    assert channel_for("company-1", "user-1") == "notifications:company-1:user-1"


def _flushed(notification):
    """Mimic what a real `db.flush()` against Postgres does: populate the
    `TimestampMixin` server-default columns the mocked repository otherwise
    leaves `None` (see `NotificationModel.created_at`)."""
    notification.created_at = datetime.now(timezone.utc)
    return notification


async def test_create_writes_then_publishes(service, repo, cache):
    repo.create.side_effect = _flushed

    notification = await service.create(
        company_id="company-1", user_id="user-1", type="draft_shared", title="Başlık", body="Gövde",
        resource_type="draft_share", resource_id="share-1",
    )

    assert notification.user_id == "user-1"
    repo.create.assert_awaited_once()
    cache.publish.assert_awaited_once()
    channel, _payload = cache.publish.await_args.args
    assert channel == "notifications:company-1:user-1"


async def test_create_without_a_cache_skips_the_publish(repo):
    service = NotificationService(repo, cache=None)
    repo.create.side_effect = _flushed

    await service.create(company_id="company-1", user_id="user-1", type="x", title="t")

    repo.create.assert_awaited_once()


async def test_mark_read_404s_when_missing(service, repo):
    repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await service.mark_read("notif-1", "company-1", "user-1")


async def test_mark_read_denies_a_different_user(service, repo):
    repo.get_by_id.return_value = _notification(user_id="someone-else")

    with pytest.raises(AuthorizationException):
        await service.mark_read("notif-1", "company-1", "user-1")


async def test_mark_read_succeeds_for_the_owner(service, repo):
    repo.get_by_id.return_value = _notification(user_id="user-1")
    repo.mark_read.side_effect = lambda n: n

    result = await service.mark_read("notif-1", "company-1", "user-1")

    assert result.user_id == "user-1"
    repo.mark_read.assert_awaited_once()


async def test_mark_all_read_delegates_to_repository(service, repo):
    repo.mark_all_read.return_value = 5

    assert await service.mark_all_read("company-1", "user-1") == 5
