"""Unit tests for RBAC clearance resolution (app.core.permissions.role_checker)."""

import pytest

from app.api.exceptions.authorization import AuthorizationException
from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.enums.user_role import UserRole
from app.core.permissions.role_checker import assert_clearance, bypasses_ownership, clearance_for
from app.domains.users.model.user_model import UserModel


def _user(role: UserRole, clearance_level: str = "hizmete_ozel") -> UserModel:
    return UserModel(
        id="u-1",
        username="u1",
        email="u1@example.com",
        hashed_password="x",
        role=role.value,
        clearance_level=clearance_level,
        is_active=True,
        is_deleted=False,
    )


# ==========================================
# clearance_for()
# ==========================================
def test_none_user_has_no_clearance():
    assert clearance_for(None) is None


def test_admin_clears_the_ceiling_regardless_of_clearance_level():
    user = _user(UserRole.ADMIN, clearance_level="unmarked")
    assert clearance_for(user) is SensitivityLevel.COK_GIZLI


def test_manager_clears_the_ceiling_same_as_admin():
    """A company manager is trusted with full access, same as an admin."""
    user = _user(UserRole.MANAGER, clearance_level="unmarked")
    assert clearance_for(user) is SensitivityLevel.COK_GIZLI


def test_employee_gets_their_own_clearance_level():
    user = _user(UserRole.EMPLOYEE, clearance_level="gizli")
    assert clearance_for(user) is SensitivityLevel.GIZLI


def test_two_employees_can_have_different_clearance():
    low = _user(UserRole.EMPLOYEE, clearance_level="tasnif_disi")
    high = _user(UserRole.EMPLOYEE, clearance_level="cok_gizli")
    assert clearance_for(low) is SensitivityLevel.TASNIF_DISI
    assert clearance_for(high) is SensitivityLevel.COK_GIZLI


def test_employee_default_clearance_matches_the_policy_default():
    user = _user(UserRole.EMPLOYEE, clearance_level="hizmete_ozel")
    assert clearance_for(user) is SensitivityLevel.HIZMETE_OZEL


def test_unrecognised_role_string_has_no_clearance():
    """Data corruption / a retired role value must degrade, not crash."""
    user = _user(UserRole.EMPLOYEE)
    user.role = "auditor"  # removed from UserRole in this phase
    assert clearance_for(user) is None


def test_employee_with_an_invalid_clearance_level_falls_back_to_the_policy_default():
    user = _user(UserRole.EMPLOYEE)
    user.clearance_level = "not-a-real-level"
    assert clearance_for(user) is SensitivityLevel.HIZMETE_OZEL


# ==========================================
# assert_clearance()
# ==========================================
def test_assert_clearance_passes_when_sufficient():
    user = _user(UserRole.EMPLOYEE, clearance_level="gizli")
    assert_clearance(user, SensitivityLevel.OZEL)  # does not raise


def test_assert_clearance_raises_when_insufficient():
    user = _user(UserRole.EMPLOYEE, clearance_level="tasnif_disi")
    with pytest.raises(AuthorizationException):
        assert_clearance(user, SensitivityLevel.GIZLI)


def test_assert_clearance_raises_for_none_user():
    with pytest.raises(AuthorizationException):
        assert_clearance(None, SensitivityLevel.UNMARKED)


def test_assert_clearance_allows_exact_match():
    user = _user(UserRole.EMPLOYEE, clearance_level="ozel")
    assert_clearance(user, SensitivityLevel.OZEL)  # does not raise


# ==========================================
# bypasses_ownership()
# ==========================================
def test_none_user_does_not_bypass_ownership():
    assert bypasses_ownership(None) is False


def test_admin_bypasses_ownership():
    assert bypasses_ownership(_user(UserRole.ADMIN)) is True


def test_manager_bypasses_ownership():
    assert bypasses_ownership(_user(UserRole.MANAGER)) is True


def test_employee_does_not_bypass_ownership():
    assert bypasses_ownership(_user(UserRole.EMPLOYEE)) is False


def test_unrecognised_role_does_not_bypass_ownership():
    user = _user(UserRole.EMPLOYEE)
    user.role = "auditor"
    assert bypasses_ownership(user) is False
