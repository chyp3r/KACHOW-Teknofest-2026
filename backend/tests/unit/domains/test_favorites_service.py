from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.conflict import ConflictException
from app.api.exceptions.not_found import NotFoundException
from app.domains.users.favorites_service import FavoriteService
from app.domains.users.model.user_favorite_model import UserFavoriteModel
from app.domains.users.model.user_model import UserModel


def _user(**overrides) -> UserModel:
    fields = dict(
        id="emp-1", company_id="company-1", username="emp1", email="emp1@example.com",
        role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False,
        hashed_password="x", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return UserModel(**fields)


@pytest.fixture
def favorite_repo():
    return AsyncMock()


@pytest.fixture
def user_repo():
    return AsyncMock()


@pytest.fixture
def service(favorite_repo, user_repo):
    return FavoriteService(favorite_repo, user_repo)


async def test_add_favorite_rejects_self(service):
    with pytest.raises(AuthorizationException):
        await service.add_favorite("company-1", _user(id="emp-1"), "emp-1", None)


async def test_add_favorite_404s_on_unknown_user(service, user_repo):
    user_repo.get_by_id_in_company.return_value = None
    with pytest.raises(NotFoundException):
        await service.add_favorite("company-1", _user(id="emp-1"), "emp-2", None)


async def test_add_favorite_rejects_duplicate(service, user_repo, favorite_repo):
    user_repo.get_by_id_in_company.return_value = _user(id="emp-2")
    favorite_repo.get.return_value = UserFavoriteModel(
        id="fav-1", company_id="company-1", owner_user_id="emp-1", favorite_user_id="emp-2", note=None
    )
    with pytest.raises(ConflictException):
        await service.add_favorite("company-1", _user(id="emp-1"), "emp-2", None)


async def test_add_favorite_creates_row(service, user_repo, favorite_repo):
    user_repo.get_by_id_in_company.return_value = _user(id="emp-2", username="emp2")
    favorite_repo.get.return_value = None
    favorite_repo.create.side_effect = lambda f: f

    favorite, user = await service.add_favorite("company-1", _user(id="emp-1"), "emp-2", "not")

    assert favorite.owner_user_id == "emp-1"
    assert favorite.favorite_user_id == "emp-2"
    assert user.id == "emp-2"


async def test_remove_favorite_404s_when_absent(service, favorite_repo):
    favorite_repo.delete.return_value = False
    with pytest.raises(NotFoundException):
        await service.remove_favorite("company-1", _user(id="emp-1"), "emp-2")


async def test_remove_favorite_succeeds(service, favorite_repo):
    favorite_repo.delete.return_value = True
    await service.remove_favorite("company-1", _user(id="emp-1"), "emp-2")
    favorite_repo.delete.assert_awaited_once_with("emp-1", "emp-2", "company-1")
