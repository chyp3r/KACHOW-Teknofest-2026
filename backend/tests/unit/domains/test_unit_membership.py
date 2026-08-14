from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.api.exceptions.conflict import ConflictException
from app.api.exceptions.not_found import NotFoundException
from app.domains.units.model.unit_membership_model import UnitMembershipModel
from app.domains.units.model.unit_model import UnitModel
from app.domains.units.service import UnitMembershipService
from app.domains.users.model.user_model import UserModel


def _unit(**overrides) -> UnitModel:
    fields = dict(id="unit-1", company_id="company-1", name="İK", description="d", is_active=True)
    fields.update(overrides)
    return UnitModel(**fields)


def _user(**overrides) -> UserModel:
    fields = dict(
        id="user-1", company_id="company-1", username="u1", email="u1@example.com",
        role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False,
        hashed_password="x", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return UserModel(**fields)


@pytest.fixture
def membership_repo():
    return AsyncMock()


@pytest.fixture
def unit_repo():
    return AsyncMock()


@pytest.fixture
def user_repo():
    return AsyncMock()


@pytest.fixture
def service(membership_repo, unit_repo, user_repo):
    return UnitMembershipService(membership_repo, unit_repo, user_repo)


async def test_add_member_404s_when_unit_missing(service, unit_repo):
    unit_repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await service.add_member("unit-1", "user-1", "company-1", is_primary=False, role_in_unit=None)


async def test_add_member_404s_when_user_missing(service, unit_repo, user_repo):
    unit_repo.get_by_id.return_value = _unit()
    user_repo.get_by_id_in_company.return_value = None

    with pytest.raises(NotFoundException):
        await service.add_member("unit-1", "user-1", "company-1", is_primary=False, role_in_unit=None)


async def test_add_member_conflicts_when_already_a_member(service, unit_repo, user_repo, membership_repo):
    unit_repo.get_by_id.return_value = _unit()
    user_repo.get_by_id_in_company.return_value = _user()
    membership_repo.get.return_value = UnitMembershipModel(
        id="m-1", company_id="company-1", unit_id="unit-1", user_id="user-1", is_primary=False
    )

    with pytest.raises(ConflictException):
        await service.add_member("unit-1", "user-1", "company-1", is_primary=False, role_in_unit=None)


async def test_add_member_clears_other_primaries_when_promoting(service, unit_repo, user_repo, membership_repo):
    unit_repo.get_by_id.return_value = _unit()
    user_repo.get_by_id_in_company.return_value = _user()
    membership_repo.get.return_value = None
    membership_repo.create.side_effect = lambda m: m

    await service.add_member("unit-1", "user-1", "company-1", is_primary=True, role_in_unit="lead")

    membership_repo.clear_primary_for_user.assert_awaited_once_with("user-1", "company-1")
    created = membership_repo.create.call_args.args[0]
    assert created.is_primary is True
    assert created.role_in_unit == "lead"


async def test_add_member_does_not_clear_primaries_when_not_promoting(service, unit_repo, user_repo, membership_repo):
    unit_repo.get_by_id.return_value = _unit()
    user_repo.get_by_id_in_company.return_value = _user()
    membership_repo.get.return_value = None
    membership_repo.create.side_effect = lambda m: m

    await service.add_member("unit-1", "user-1", "company-1", is_primary=False, role_in_unit=None)

    membership_repo.clear_primary_for_user.assert_not_awaited()


async def test_remove_member_404s_when_nothing_deleted(service, membership_repo):
    membership_repo.delete.return_value = False

    with pytest.raises(NotFoundException):
        await service.remove_member("unit-1", "user-1", "company-1")


async def test_list_members_404s_when_unit_missing(service, unit_repo):
    unit_repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await service.list_members("unit-1", "company-1")


async def test_list_members_returns_the_repository_result(service, unit_repo, membership_repo):
    unit_repo.get_by_id.return_value = _unit()
    expected = [(UnitMembershipModel(id="m-1", company_id="company-1", unit_id="unit-1", user_id="user-1"), _user())]
    membership_repo.list_for_unit.return_value = expected

    result = await service.list_members("unit-1", "company-1")

    assert result == expected
