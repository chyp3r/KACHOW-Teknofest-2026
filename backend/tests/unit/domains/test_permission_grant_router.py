"""HTTP-level tests for the permission-grant management endpoints
(POST/GET /users/{user_id}/permissions, DELETE /users/permissions/{grant_id}).

Same standalone-app + dependency_overrides pattern as test_user_router.py.
`require_roles` itself is never overridden (that override is a no-op --
see test_company_router.py's own note): the employee-is-refused case below
exercises the real require_roles(ADMIN, MANAGER) closure via get_current_user.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependency import get_authz_service, get_current_user, get_db
from app.api.exceptions import BaseAppException, app_exception_handler
from app.core.authz.engine import Decision
from app.core.enums.user_role import UserRole
from app.domains.users.model.user_model import UserModel
from app.domains.users.router import router

app = FastAPI()
app.add_exception_handler(BaseAppException, app_exception_handler)
app.include_router(router)


async def mock_get_db():
    yield AsyncMock()


def _user(user_id: str, role: UserRole, company_id: str = "company-1") -> UserModel:
    return UserModel(
        id=user_id,
        company_id=company_id,
        username=user_id,
        email=f"{user_id}@example.com",
        role=role.value,
        clearance_level="hizmete_ozel",
        is_active=True,
        is_deleted=False,
        hashed_password="pw",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _admin():
    return _user("admin-1", UserRole.ADMIN)


class _FakeAuthzService:
    """Stand-in for AuthzService with a scriptable authorize() outcome."""

    def __init__(self, permit: bool = True):
        self.permit = permit
        self.invalidate_calls: list[str] = []

    async def authorize(self, subject, action, resource, env=None):
        return Decision(permit=self.permit, reason="test")

    async def invalidate_company(self, company_id: str) -> None:
        self.invalidate_calls.append(company_id)


app.dependency_overrides[get_db] = mock_get_db
app.dependency_overrides[get_current_user] = _admin
app.dependency_overrides[get_authz_service] = lambda: _FakeAuthzService(permit=True)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_overrides():
    app.dependency_overrides[get_current_user] = _admin
    app.dependency_overrides[get_authz_service] = lambda: _FakeAuthzService(permit=True)
    yield


@patch("app.domains.users.router.PermissionGrantRepository")
@patch("app.domains.users.router.UserRepository")
def test_grant_permission_succeeds_for_a_company_member(mock_user_repo_cls, mock_grant_repo_cls):
    mock_user_repo = mock_user_repo_cls.return_value
    mock_user_repo.get_by_id_in_company = AsyncMock(return_value=_user("emp-1", UserRole.EMPLOYEE))

    async def _create(grant):
        grant.id = "grant-1"
        grant.created_at = datetime.now(timezone.utc)
        return grant

    mock_grant_repo = mock_grant_repo_cls.return_value
    mock_grant_repo.create = AsyncMock(side_effect=_create)

    payload = {
        "action": "document:delete",
        "resource_type": "document",
        "resource_selector": {"any": True},
    }
    response = client.post("/users/emp-1/permissions", json=payload)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["action"] == "document:delete"
    assert data["subject_id"] == "emp-1"
    assert data["granted_by"] == "admin-1"
    mock_grant_repo.create.assert_awaited_once()


@patch("app.domains.users.router.UserRepository")
def test_grant_permission_404s_for_a_user_outside_the_company(mock_user_repo_cls):
    mock_user_repo = mock_user_repo_cls.return_value
    mock_user_repo.get_by_id_in_company = AsyncMock(return_value=None)

    payload = {"action": "document:delete", "resource_type": "document"}
    response = client.post("/users/ghost/permissions", json=payload)

    assert response.status_code == 404


@patch("app.domains.users.router.UserRepository")
def test_grant_permission_refuses_privilege_escalation(mock_user_repo_cls):
    """The granter cannot delegate an action it is not itself authorized for."""
    app.dependency_overrides[get_authz_service] = lambda: _FakeAuthzService(permit=False)
    mock_user_repo = mock_user_repo_cls.return_value
    mock_user_repo.get_by_id_in_company = AsyncMock(return_value=_user("emp-1", UserRole.EMPLOYEE))

    payload = {"action": "document:delete", "resource_type": "document"}
    response = client.post("/users/emp-1/permissions", json=payload)

    assert response.status_code == 403


def test_grant_permission_refuses_an_employee_caller():
    """require_roles(ADMIN, MANAGER) rejects an EMPLOYEE caller before any handler logic runs."""
    app.dependency_overrides[get_current_user] = lambda: _user("emp-1", UserRole.EMPLOYEE)

    payload = {"action": "document:delete", "resource_type": "document"}
    response = client.post("/users/emp-2/permissions", json=payload)

    assert response.status_code == 403


def test_grant_permission_rejects_an_unknown_action():
    payload = {"action": "not:a:real:action", "resource_type": "document"}
    response = client.post("/users/emp-1/permissions", json=payload)

    assert response.status_code == 422


@patch("app.domains.users.router.PermissionGrantRepository")
def test_list_permissions_returns_the_users_grants(mock_grant_repo_cls):
    mock_grant_repo = mock_grant_repo_cls.return_value
    row = MagicMock()
    row.id = "grant-1"
    row.company_id = "company-1"
    row.subject_type = "user"
    row.subject_id = "emp-1"
    row.action = "document:delete"
    row.resource_type = "document"
    row.resource_selector = {"any": True}
    row.effect = "permit"
    row.priority = 0
    row.valid_from = None
    row.valid_until = None
    row.granted_by = "admin-1"
    row.revoked_at = None
    row.reason = None
    row.created_at = datetime.now(timezone.utc)
    mock_grant_repo.list_for_user = AsyncMock(return_value=[row])

    response = client.get("/users/emp-1/permissions")

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == "grant-1"


@patch("app.domains.users.router.PermissionGrantRepository")
def test_revoke_permission_succeeds(mock_grant_repo_cls):
    mock_grant_repo = mock_grant_repo_cls.return_value
    mock_grant_repo.revoke = AsyncMock(return_value=True)

    response = client.delete("/users/permissions/grant-1")

    assert response.status_code == 200
    mock_grant_repo.revoke.assert_awaited_once_with("grant-1", "company-1")


@patch("app.domains.users.router.PermissionGrantRepository")
def test_revoke_permission_404s_when_not_found(mock_grant_repo_cls):
    mock_grant_repo = mock_grant_repo_cls.return_value
    mock_grant_repo.revoke = AsyncMock(return_value=False)

    response = client.delete("/users/permissions/missing")

    assert response.status_code == 404
