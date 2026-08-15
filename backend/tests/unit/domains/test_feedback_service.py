from unittest.mock import AsyncMock

import pytest

from app.api.exceptions.not_found import NotFoundException
from app.domains.feedback.model.feedback_model import FeedbackModel
from app.domains.feedback.service import FeedbackService, _hash_content


def _feedback(**overrides) -> FeedbackModel:
    fields = dict(
        id="fb-1", company_id="company-1", user_id="user-1", session_id=None,
        message_id=None, draft_id=None, target_kind="draft", signal="like",
        comment=None, dimensions=None, content_hash=_hash_content("Sayın Makam,"),
        context=None, is_deleted=False,
    )
    fields.update(overrides)
    return FeedbackModel(**fields)


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def service(repo):
    return FeedbackService(repo)


def test_hash_content_is_deterministic_and_whitespace_insensitive():
    assert _hash_content("Sayın Makam,") == _hash_content("Sayın Makam,")
    assert _hash_content("Sayın Makam,") == _hash_content("  Sayın Makam,  ")
    assert _hash_content("Sayın Makam,") != _hash_content("Sayın Makam!")


async def test_submit_creates_a_new_row_when_no_prior_vote_exists(service, repo):
    repo.find_existing_vote.return_value = None
    repo.create.side_effect = lambda feedback: feedback

    result = await service.submit(
        company_id="company-1", user_id="user-1", target_kind="draft", signal="like",
        content="Sayın Makam,",
    )

    assert result.signal == "like"
    assert result.content_hash == _hash_content("Sayın Makam,")
    repo.create.assert_awaited_once()
    repo.update_vote.assert_not_awaited()


async def test_submit_upserts_onto_an_existing_vote_on_the_same_text():
    """The bug this guards against: re-voting on the same rated text (or
    clicking 👍 then 👎) must never hit the uq_feedback_vote_identity
    constraint -- it should update the one existing row instead."""
    repo = AsyncMock()
    service = FeedbackService(repo)
    existing = _feedback(signal="like")
    repo.find_existing_vote.return_value = existing
    repo.update_vote.side_effect = lambda feedback, **kwargs: feedback

    result = await service.submit(
        company_id="company-1", user_id="user-1", target_kind="draft", signal="dislike",
        content="Sayın Makam,", comment="Üslup çok resmi değil.",
    )

    assert result is existing
    repo.create.assert_not_awaited()
    repo.update_vote.assert_awaited_once()
    call_kwargs = repo.update_vote.await_args.kwargs
    assert call_kwargs["signal"] == "dislike"
    assert call_kwargs["comment"] == "Üslup çok resmi değil."


async def test_submit_scopes_the_dedup_lookup_to_company_user_and_target_kind(service, repo):
    repo.find_existing_vote.return_value = None
    repo.create.side_effect = lambda feedback: feedback

    await service.submit(
        company_id="company-1", user_id="user-1", target_kind="revision", signal="like",
        content="Taslak metni",
    )

    repo.find_existing_vote.assert_awaited_once_with(
        "company-1", "user-1", "revision", _hash_content("Taslak metni")
    )


async def test_remove_404s_when_missing(service, repo):
    repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await service.remove("fb-1", "company-1")


async def test_remove_soft_deletes_an_existing_row(service, repo):
    feedback = _feedback()
    repo.get_by_id.return_value = feedback

    result = await service.remove("fb-1", "company-1")

    assert result is feedback
    repo.soft_delete.assert_awaited_once_with(feedback)


async def test_stats_combines_signal_and_target_kind_breakdowns(service, repo):
    repo.count_by_signal.return_value = {"like": 8, "dislike": 2}
    repo.count_by_target_kind.return_value = {"draft": 6, "assist_reply": 4}

    result = await service.stats("company-1")

    assert result == {
        "total": 10,
        "likes": 8,
        "dislikes": 2,
        "by_target_kind": {"draft": 6, "assist_reply": 4},
    }


async def test_stats_defaults_to_zero_when_no_votes_exist(service, repo):
    repo.count_by_signal.return_value = {}
    repo.count_by_target_kind.return_value = {}

    result = await service.stats("company-1")

    assert result == {"total": 0, "likes": 0, "dislikes": 0, "by_target_kind": {}}
