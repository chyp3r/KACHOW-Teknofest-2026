from unittest.mock import MagicMock

import pytest

from app.api.exceptions.authorization import AuthorizationException
from app.core.enums.user_role import UserRole
from app.domains.feedback.router import _require_company_access


def _user(role: UserRole, company_id: str):
    user = MagicMock()
    user.role = role.value
    user.company_id = company_id
    return user


def test_root_may_read_any_companys_feedback_stats():
    root = _user(UserRole.ROOT, company_id=None)

    _require_company_access(root, "some-other-company")  # does not raise


def test_admin_may_read_its_own_companys_stats():
    admin = _user(UserRole.ADMIN, company_id="company-1")

    _require_company_access(admin, "company-1")  # does not raise


def test_admin_cannot_read_another_companys_stats():
    admin = _user(UserRole.ADMIN, company_id="company-1")

    with pytest.raises(AuthorizationException):
        _require_company_access(admin, "some-other-company")


def test_manager_cannot_read_another_companys_stats():
    manager = _user(UserRole.MANAGER, company_id="company-1")

    with pytest.raises(AuthorizationException):
        _require_company_access(manager, "some-other-company")


def test_employee_cannot_read_any_companys_stats():
    employee = _user(UserRole.EMPLOYEE, company_id="company-1")

    with pytest.raises(AuthorizationException):
        _require_company_access(employee, "company-1")
