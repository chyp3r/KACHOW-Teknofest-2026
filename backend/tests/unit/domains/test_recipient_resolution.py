from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.domains.transfers.recipient_resolution import RecipientResolutionService
from app.domains.users.model.user_model import UserModel


def _user(**overrides) -> UserModel:
    fields = dict(
        id="emp-1", company_id="company-1", username="ahmet.yilmaz", email="ahmet@example.com",
        role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False,
        hashed_password="x", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return UserModel(**fields)


@pytest.fixture
def user_repo():
    return AsyncMock()


@pytest.fixture
def favorite_repo():
    repo = AsyncMock()
    repo.is_favorite.return_value = False
    return repo


@pytest.fixture
def service(user_repo, favorite_repo):
    return RecipientResolutionService(user_repo, favorite_repo)


async def test_empty_name_is_not_found(service):
    result = await service.resolve(name="   ", company_id="company-1", requester_id="me")
    assert result.status == "not_found"
    assert result.candidates == ()


async def test_no_matches_is_not_found(service, user_repo):
    user_repo.search.return_value = []
    result = await service.resolve(name="kimse-yok", company_id="company-1", requester_id="me")
    assert result.status == "not_found"


async def test_a_single_match_resolves(service, user_repo):
    user_repo.search.return_value = [(_user(id="u1", username="ahmet.yilmaz"), "İK")]
    result = await service.resolve(name="ahmet.yilmaz", company_id="company-1", requester_id="me")
    assert result.status == "resolved"
    assert len(result.candidates) == 1
    assert result.candidates[0].user_id == "u1"
    assert result.candidates[0].unit_name == "İK"


async def test_multiple_substring_matches_are_ambiguous(service, user_repo):
    user_repo.search.return_value = [
        (_user(id="u1", username="ahmet.yilmaz"), "İK"),
        (_user(id="u2", username="ahmet.demir"), "BT"),
    ]
    result = await service.resolve(name="ahmet", company_id="company-1", requester_id="me")
    assert result.status == "ambiguous"
    assert {c.user_id for c in result.candidates} == {"u1", "u2"}


async def test_an_exact_username_match_wins_over_a_broader_substring_search(service, user_repo):
    """Typing the recipient's full username never counts as ambiguous just
    because a substring search would also surface unrelated partial
    matches."""
    user_repo.search.return_value = [
        (_user(id="u1", username="ahmet.yilmaz"), "İK"),
        (_user(id="u2", username="ahmet.demir"), "BT"),
    ]
    result = await service.resolve(name="ahmet.yilmaz", company_id="company-1", requester_id="me")
    assert result.status == "resolved"
    assert result.candidates[0].user_id == "u1"


async def test_exact_match_is_case_insensitive(service, user_repo):
    user_repo.search.return_value = [(_user(id="u1", username="Ahmet.Yilmaz"), None)]
    result = await service.resolve(name="ahmet.yilmaz", company_id="company-1", requester_id="me")
    assert result.status == "resolved"


async def test_favorites_are_ranked_ahead_of_non_favorites(service, user_repo, favorite_repo):
    user_repo.search.return_value = [
        (_user(id="u1", username="ahmet.a"), None),
        (_user(id="u2", username="ahmet.b"), None),
    ]
    favorite_repo.is_favorite.side_effect = lambda owner, favorite_user_id, company_id: favorite_user_id == "u2"

    result = await service.resolve(name="ahmet", company_id="company-1", requester_id="me")

    assert result.status == "ambiguous"
    assert result.candidates[0].user_id == "u2"
    assert result.candidates[0].is_favorite is True
    assert result.candidates[1].is_favorite is False
