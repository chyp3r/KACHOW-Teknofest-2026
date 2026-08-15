from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.feedback.model.feedback_model import FeedbackModel
from app.domains.feedback.repository import FeedbackRepository


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def repo(mock_session):
    return FeedbackRepository(mock_session)


def _feedback(**overrides) -> FeedbackModel:
    fields = dict(
        id="fb-1", company_id="company-1", user_id="user-1", session_id=None,
        message_id=None, draft_id=None, target_kind="draft", signal="like",
        comment=None, dimensions=None, content_hash="abc123", context=None,
        is_deleted=False,
    )
    fields.update(overrides)
    return FeedbackModel(**fields)


async def test_create_adds_and_flushes(repo, mock_session):
    feedback = _feedback()

    result = await repo.create(feedback)

    assert result is feedback
    mock_session.add.assert_called_once_with(feedback)
    mock_session.flush.assert_awaited_once()


async def test_find_existing_vote_returns_the_matching_row(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = _feedback()
    mock_session.execute.return_value = mock_result

    result = await repo.find_existing_vote("company-1", "user-1", "draft", "abc123")

    assert result is not None
    assert result.content_hash == "abc123"


async def test_update_vote_overwrites_fields_and_undeletes(repo, mock_session):
    feedback = _feedback(signal="like", is_deleted=True)

    result = await repo.update_vote(
        feedback, signal="dislike", comment="daha resmi olmali", dimensions={"uslup": True},
        context={"correspondence_type": "cover_letter"},
    )

    assert result.signal == "dislike"
    assert result.comment == "daha resmi olmali"
    assert result.dimensions == {"uslup": True}
    assert result.is_deleted is False
    mock_session.flush.assert_awaited_once()


async def test_soft_delete_marks_and_flushes(repo, mock_session):
    feedback = _feedback(is_deleted=False)

    await repo.soft_delete(feedback)

    assert feedback.is_deleted is True
    mock_session.flush.assert_awaited_once()


async def test_list_filtered_returns_rows(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [_feedback()]
    mock_session.execute.return_value = mock_result

    result = await repo.list_filtered("company-1")

    assert len(result) == 1


async def test_count_by_signal_returns_a_dict(repo, mock_session):
    mock_result = MagicMock()
    mock_result.all.return_value = [("like", 7), ("dislike", 3)]
    mock_session.execute.return_value = mock_result

    result = await repo.count_by_signal("company-1")

    assert result == {"like": 7, "dislike": 3}


async def test_count_by_target_kind_returns_a_dict(repo, mock_session):
    mock_result = MagicMock()
    mock_result.all.return_value = [("draft", 5), ("assist_reply", 2)]
    mock_session.execute.return_value = mock_result

    result = await repo.count_by_target_kind("company-1")

    assert result == {"draft": 5, "assist_reply": 2}
