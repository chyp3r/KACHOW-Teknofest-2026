from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.domains.drafts.model.draft_model import DraftModel
from app.domains.transfers.recommendation import RecipientRecommendationService
from app.domains.units.model.unit_membership_model import UnitMembershipModel
from app.domains.units.model.unit_model import UnitModel
from app.domains.users.model.user_favorite_model import UserFavoriteModel
from app.domains.users.model.user_model import UserModel


def _draft(**overrides) -> DraftModel:
    fields = dict(
        id="draft-1", company_id="company-1", user_id="emp-1", session_id=None, document_id=None,
        version=1, content="içerik", destination=None, destination_unit_id=None,
        destination_justification=None, correspondence_type=None, is_deleted=False,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return DraftModel(**fields)


def _user(user_id: str, username: str) -> UserModel:
    return UserModel(
        id=user_id, company_id="company-1", username=username, email=f"{username}@example.com",
        role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False,
        hashed_password="x",
    )


def _membership(user_id: str) -> UnitMembershipModel:
    return UnitMembershipModel(
        id=f"mem-{user_id}", company_id="company-1", unit_id="unit-a", user_id=user_id, is_primary=False,
    )


@pytest.fixture
def draft_repo():
    return AsyncMock()


@pytest.fixture
def unit_repo():
    repo = AsyncMock()
    repo.get_by_id.return_value = UnitModel(
        id="unit-a", company_id="company-1", name="Mali İşler", description="x", is_active=True
    )
    return repo


@pytest.fixture
def unit_membership_repo():
    return AsyncMock()


@pytest.fixture
def favorite_repo():
    repo = AsyncMock()
    repo.list_for_owner.return_value = []
    return repo


@pytest.fixture
def service(draft_repo, unit_repo, unit_membership_repo, favorite_repo):
    return RecipientRecommendationService(draft_repo, unit_repo, unit_membership_repo, favorite_repo)


async def test_empty_when_draft_missing(service, draft_repo):
    draft_repo.get_by_id.return_value = None
    result = await service.recommend_for_draft("draft-1", "company-1", "me")
    assert result == []


async def test_empty_when_draft_belongs_to_another_company(service, draft_repo):
    draft_repo.get_by_id.return_value = _draft(company_id="company-2")
    result = await service.recommend_for_draft("draft-1", "company-1", "me")
    assert result == []


async def test_empty_when_draft_was_never_routed(service, draft_repo, unit_repo):
    draft_repo.get_by_id.return_value = _draft(destination_unit_id=None)
    result = await service.recommend_for_draft("draft-1", "company-1", "me")
    assert result == []
    unit_repo.get_by_id.assert_not_awaited()


async def test_empty_when_the_routed_unit_is_inactive(service, draft_repo, unit_repo):
    draft_repo.get_by_id.return_value = _draft(destination_unit_id="unit-a")
    unit_repo.get_by_id.return_value = UnitModel(
        id="unit-a", company_id="company-1", name="Mali İşler", description="x", is_active=False
    )
    result = await service.recommend_for_draft("draft-1", "company-1", "me")
    assert result == []


async def test_ranks_favorites_ahead_of_plain_members(
    service, draft_repo, unit_membership_repo, favorite_repo
):
    draft_repo.get_by_id.return_value = _draft(destination_unit_id="unit-a")
    unit_membership_repo.list_for_unit.return_value = [
        (_membership("u1"), _user("u1", "ahmet")),
        (_membership("u2"), _user("u2", "berk")),
    ]
    favorite_repo.list_for_owner.return_value = [
        (UserFavoriteModel(id="f1", company_id="company-1", owner_user_id="me", favorite_user_id="u2"), _user("u2", "berk")),
    ]

    result = await service.recommend_for_draft("draft-1", "company-1", "me")

    assert [r.user_id for r in result] == ["u2", "u1"]
    assert result[0].source == "favorite_in_unit"
    assert result[1].source == "unit_member"


async def test_excludes_the_requester_from_their_own_recommendations(service, draft_repo, unit_membership_repo):
    draft_repo.get_by_id.return_value = _draft(destination_unit_id="unit-a")
    unit_membership_repo.list_for_unit.return_value = [
        (_membership("me"), _user("me", "istekte-bulunan")),
        (_membership("u1"), _user("u1", "ahmet")),
    ]
    result = await service.recommend_for_draft("draft-1", "company-1", "me")
    assert [r.user_id for r in result] == ["u1"]


async def test_respects_the_limit(service, draft_repo, unit_membership_repo):
    draft_repo.get_by_id.return_value = _draft(destination_unit_id="unit-a")
    unit_membership_repo.list_for_unit.return_value = [
        (_membership(f"u{i}"), _user(f"u{i}", f"user{i}")) for i in range(10)
    ]
    result = await service.recommend_for_draft("draft-1", "company-1", "me", limit=3)
    assert len(result) == 3
