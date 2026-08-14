from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.model.draft_share_model import DraftShareModel
from app.domains.drafts.repository import DraftShareRepository


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def repo(mock_session):
    return DraftShareRepository(mock_session)


def _share(**overrides) -> DraftShareModel:
    fields = dict(
        id="share-1", company_id="company-1", draft_id="draft-1", sender_id="sender-1",
        recipient_id="recipient-1", suggested_unit_id=None, message=None, status="sent",
        responded_at=None, response_note=None,
    )
    fields.update(overrides)
    return DraftShareModel(**fields)


def _draft(**overrides) -> DraftModel:
    fields = dict(
        id="draft-1", company_id="company-1", user_id="sender-1", session_id=None,
        document_id=None, version=1, content="içerik", is_deleted=False,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return DraftModel(**fields)


async def test_create_adds_and_flushes(repo, mock_session):
    share = _share()

    result = await repo.create(share)

    assert result is share
    mock_session.add.assert_called_once_with(share)
    mock_session.flush.assert_awaited_once()


async def test_get_by_id_returns_none_when_missing(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    assert await repo.get_by_id("missing", "company-1") is None


async def test_list_inbox_joins_draft(repo, mock_session):
    share, draft = _share(), _draft()
    mock_result = MagicMock()
    mock_result.all.return_value = [(share, draft)]
    mock_session.execute.return_value = mock_result

    result = await repo.list_inbox("company-1", "recipient-1")

    assert result == [(share, draft)]


async def test_count_inbox_returns_scalar(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 3
    mock_session.execute.return_value = mock_result

    assert await repo.count_inbox("company-1", "recipient-1") == 3


async def test_mark_read_advances_sent_to_read(repo, mock_session):
    share = _share(status="sent")

    result = await repo.mark_read(share)

    assert result.status == "read"
    mock_session.flush.assert_awaited_once()


async def test_mark_read_is_a_noop_past_sent(repo, mock_session):
    share = _share(status="accepted")

    result = await repo.mark_read(share)

    assert result.status == "accepted"


async def test_respond_sets_status_note_and_timestamp(repo, mock_session):
    share = _share(status="sent")

    result = await repo.respond(share, "accepted", "tamam")

    assert result.status == "accepted"
    assert result.response_note == "tamam"
    assert result.responded_at is not None


async def test_withdraw_sets_status(repo, mock_session):
    share = _share(status="sent")

    result = await repo.withdraw(share)

    assert result.status == "withdrawn"
