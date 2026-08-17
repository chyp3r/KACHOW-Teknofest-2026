from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.enums.sensitivity_level import SensitivityLevel
from app.domains.transfers.policy import TransferPolicy
from app.domains.units.model.unit_membership_model import UnitMembershipModel
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
def unit_membership_repo():
    repo = AsyncMock()
    repo.get_primary_for_user.return_value = None
    return repo


@pytest.fixture
def favorite_repo():
    repo = AsyncMock()
    repo.is_favorite.return_value = False
    return repo


@pytest.fixture
def policy(unit_membership_repo, favorite_repo):
    return TransferPolicy(unit_membership_repo, favorite_repo)


async def test_denies_self_transfer(policy):
    sender = _user(id="emp-1")
    decision = await policy.evaluate(
        sender=sender, recipient=sender, company_id="company-1", channel="chat"
    )
    assert decision.permit is False
    assert decision.reason_code == "self_transfer"


async def test_denies_an_inactive_recipient(policy):
    decision = await policy.evaluate(
        sender=_user(id="emp-1"),
        recipient=_user(id="emp-2", is_active=False),
        company_id="company-1",
        channel="chat",
    )
    assert decision.permit is False
    assert decision.reason_code == "recipient_inactive"


async def test_denies_a_soft_deleted_recipient(policy):
    decision = await policy.evaluate(
        sender=_user(id="emp-1"),
        recipient=_user(id="emp-2", is_deleted=True),
        company_id="company-1",
        channel="chat",
    )
    assert decision.permit is False
    assert decision.reason_code == "recipient_inactive"


async def test_denies_insufficient_clearance(policy):
    decision = await policy.evaluate(
        sender=_user(id="emp-1"),
        recipient=_user(id="emp-2", clearance_level="tasnif_disi"),
        company_id="company-1",
        channel="chat",
        artifact_sensitivity=SensitivityLevel.GIZLI,
    )
    assert decision.permit is False
    assert decision.reason_code == "clearance"


async def test_permits_sufficient_clearance(policy):
    decision = await policy.evaluate(
        sender=_user(id="emp-1"),
        recipient=_user(id="emp-2", clearance_level="cok_gizli"),
        company_id="company-1",
        channel="chat",
        artifact_sensitivity=SensitivityLevel.GIZLI,
    )
    assert decision.permit is True


async def test_skips_clearance_check_when_artifact_has_no_sensitivity(policy):
    """A draft (no clearance concept in this system) never triggers the
    clearance deny, regardless of the recipient's own level."""
    decision = await policy.evaluate(
        sender=_user(id="emp-1"),
        recipient=_user(id="emp-2", clearance_level="tasnif_disi"),
        company_id="company-1",
        channel="chat",
        artifact_sensitivity=None,
    )
    assert decision.permit is True


async def test_ai_channel_requires_a_favorite(policy, favorite_repo):
    favorite_repo.is_favorite.return_value = False
    decision = await policy.evaluate(
        sender=_user(id="emp-1"), recipient=_user(id="emp-2"), company_id="company-1", channel="ai",
    )
    assert decision.permit is False
    assert decision.reason_code == "favorite_required"


async def test_ai_channel_permits_a_favorite(policy, favorite_repo):
    favorite_repo.is_favorite.return_value = True
    decision = await policy.evaluate(
        sender=_user(id="emp-1"), recipient=_user(id="emp-2"), company_id="company-1", channel="ai",
    )
    assert decision.permit is True


@pytest.mark.parametrize("channel", ["chat", "rest"])
async def test_favorite_is_not_required_outside_the_ai_channel(policy, favorite_repo, channel):
    favorite_repo.is_favorite.return_value = False
    decision = await policy.evaluate(
        sender=_user(id="emp-1"), recipient=_user(id="emp-2"), company_id="company-1", channel=channel,
    )
    assert decision.permit is True
    favorite_repo.is_favorite.assert_not_awaited()


async def test_cross_unit_true_when_recipient_primary_unit_differs(policy, unit_membership_repo):
    unit_membership_repo.get_primary_for_user.return_value = UnitMembershipModel(
        id="mem-1", company_id="company-1", unit_id="unit-b", user_id="emp-2", is_primary=True,
    )
    decision = await policy.evaluate(
        sender=_user(id="emp-1"),
        recipient=_user(id="emp-2"),
        company_id="company-1",
        channel="chat",
        artifact_destination_unit_id="unit-a",
    )
    assert decision.cross_unit is True
    assert decision.permit is True


async def test_cross_unit_false_when_recipient_primary_unit_matches(policy, unit_membership_repo):
    unit_membership_repo.get_primary_for_user.return_value = UnitMembershipModel(
        id="mem-1", company_id="company-1", unit_id="unit-a", user_id="emp-2", is_primary=True,
    )
    decision = await policy.evaluate(
        sender=_user(id="emp-1"),
        recipient=_user(id="emp-2"),
        company_id="company-1",
        channel="chat",
        artifact_destination_unit_id="unit-a",
    )
    assert decision.cross_unit is False


async def test_cross_unit_false_when_artifact_has_no_destination_unit(policy, unit_membership_repo):
    decision = await policy.evaluate(
        sender=_user(id="emp-1"),
        recipient=_user(id="emp-2"),
        company_id="company-1",
        channel="chat",
        artifact_destination_unit_id=None,
    )
    assert decision.cross_unit is False
    unit_membership_repo.get_primary_for_user.assert_not_awaited()


async def test_cross_unit_false_when_recipient_has_no_primary_unit(policy, unit_membership_repo):
    unit_membership_repo.get_primary_for_user.return_value = None
    decision = await policy.evaluate(
        sender=_user(id="emp-1"),
        recipient=_user(id="emp-2"),
        company_id="company-1",
        channel="chat",
        artifact_destination_unit_id="unit-a",
    )
    assert decision.cross_unit is False


async def test_cross_unit_is_still_computed_on_a_denied_decision(policy, unit_membership_repo):
    """A caller building a Faz 4 confirmation prompt needs `cross_unit`
    even when the decision itself denies for an unrelated reason."""
    unit_membership_repo.get_primary_for_user.return_value = UnitMembershipModel(
        id="mem-1", company_id="company-1", unit_id="unit-b", user_id="emp-2", is_primary=True,
    )
    decision = await policy.evaluate(
        sender=_user(id="emp-1"),
        recipient=_user(id="emp-2", is_active=False),
        company_id="company-1",
        channel="chat",
        artifact_destination_unit_id="unit-a",
    )
    assert decision.permit is False
    assert decision.cross_unit is True
