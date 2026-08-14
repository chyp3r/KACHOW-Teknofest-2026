from unittest.mock import MagicMock

from app.core.enums.user_role import UserRole
from app.domains.audit.router import _scoped_company_id


def _user(role: UserRole, company_id: str):
    user = MagicMock()
    user.role = role.value
    user.company_id = company_id
    return user


def test_root_may_request_any_companys_audit_trail():
    root = _user(UserRole.ROOT, company_id=None)

    assert _scoped_company_id(root, "some-other-company") == "some-other-company"


def test_root_omitting_company_id_gets_no_filter():
    root = _user(UserRole.ROOT, company_id=None)

    assert _scoped_company_id(root, None) is None


def test_admin_is_forced_to_its_own_company_even_when_requesting_none():
    admin = _user(UserRole.ADMIN, company_id="admin-co")

    assert _scoped_company_id(admin, None) == "admin-co"


def test_admin_cannot_override_its_scope_by_requesting_a_different_company():
    """The one place a query parameter could otherwise leak another
    company's audit trail -- ADMIN's own request value must be ignored
    entirely, not merely validated."""
    admin = _user(UserRole.ADMIN, company_id="admin-co")

    assert _scoped_company_id(admin, "some-other-company") == "admin-co"
