import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from app.domains.users.router import router
from app.api.dependency import get_current_user, require_roles, get_db
from app.domains.users.model.user_model import UserModel
from app.core.enums.user_role import UserRole
from app.api.exceptions import BaseAppException, app_exception_handler

# Create test app
app = FastAPI()
app.add_exception_handler(BaseAppException, app_exception_handler)
app.include_router(router)

# Mock dependencies
async def mock_get_db():
    yield AsyncMock()

def mock_get_current_user_admin():
    user = UserModel(id="admin-1", company_id="company-1", username="admin", email="a@a.com", role=UserRole.ADMIN.value, clearance_level="hizmete_ozel", is_active=True, is_deleted=False, hashed_password="pw", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    return user

def mock_get_current_user_employee():
    user = UserModel(id="emp-1", company_id="company-1", username="emp1", email="e@e.com", role=UserRole.EMPLOYEE.value, clearance_level="hizmete_ozel", is_active=True, is_deleted=False, hashed_password="pw", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    return user

def mock_require_roles_admin():
    def role_checker():
        return mock_get_current_user_admin()
    return role_checker

# Override dependencies
app.dependency_overrides[get_db] = mock_get_db
app.dependency_overrides[get_current_user] = mock_get_current_user_admin
app.dependency_overrides[require_roles] = mock_require_roles_admin

client = TestClient(app)

@pytest.fixture
def override_as_employee():
    app.dependency_overrides[get_current_user] = mock_get_current_user_employee
    app.dependency_overrides[require_roles] = mock_get_current_user_employee
    yield
    app.dependency_overrides[get_current_user] = mock_get_current_user_admin
    app.dependency_overrides[require_roles] = mock_require_roles_admin

@patch("app.domains.users.router.UserService")
@patch("app.domains.users.router.UserRepository")
def test_register_user(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_user = UserModel(id="1", username="testuser", email="test@example.com", role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False, hashed_password="x", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    mock_service.register_user = AsyncMock(return_value=mock_user)
    
    payload = {
        "username": "testuser",
        "email": "test@example.com",
        "password": "password123",
        "role": "employee"
    }
    response = client.post("/users", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["username"] == "testuser"
    mock_service.register_user.assert_called_once()

@patch("app.domains.users.router.UserService")
@patch("app.domains.users.router.UserRepository")
def test_invite_user(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_invite = MagicMock()
    mock_invite.id = "i-1"
    mock_invite.email = "new@example.com"
    mock_invite.role = "employee"
    mock_invite.company_id = "company-1"
    mock_invite.is_used = False
    mock_invite.created_at = datetime.now(timezone.utc)
    mock_invite.updated_at = datetime.now(timezone.utc)
    mock_service.invite_user_email = AsyncMock(return_value=mock_invite)
    
    payload = {"email": "new@example.com", "role": "employee"}
    response = client.post("/users/invitations", json=payload)
    
    assert response.status_code == 200
    assert response.json()["data"]["email"] == "new@example.com"

@patch("app.domains.users.router.UserService")
@patch("app.domains.users.router.UserRepository")
def test_list_users(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_user = UserModel(id="1", username="u1", email="u1@e.com", role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False, hashed_password="x", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    mock_service.get_users = AsyncMock(return_value=[mock_user])
    
    response = client.get("/users?skip=0&limit=10")
    
    assert response.status_code == 200
    assert len(response.json()["data"]) == 1
    assert response.json()["data"][0]["username"] == "u1"

@patch("app.domains.users.router.UserService")
@patch("app.domains.users.router.UserRepository")
def test_get_me(mock_repo_cls, mock_service_cls):
    response = client.get("/users/me")
    assert response.status_code == 200
    assert response.json()["data"]["id"] == "admin-1"

@patch("app.domains.users.router.UserService")
@patch("app.domains.users.router.UserRepository")
def test_get_user_as_admin(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_user = UserModel(id="emp-1", username="emp1", email="e@e.com", role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False, hashed_password="x", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    mock_service.get_user_by_id_in_company = AsyncMock(return_value=mock_user)

    response = client.get("/users/emp-1")
    assert response.status_code == 200
    assert response.json()["data"]["id"] == "emp-1"

@patch("app.domains.users.router.UserService")
@patch("app.domains.users.router.UserRepository")
def test_get_user_as_employee_unauthorized(mock_repo_cls, mock_service_cls, override_as_employee):
    response = client.get("/users/other-emp")
    assert response.status_code == 403

@patch("app.domains.users.router.UserService")
@patch("app.domains.users.router.UserRepository")
def test_update_user_as_admin(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_user = UserModel(id="emp-1", username="emp1", email="e@e.com", role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False, hashed_password="x", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    mock_service.update_user = AsyncMock(return_value=mock_user)
    
    payload = {"role": "manager"}
    response = client.put("/users/emp-1", json=payload)
    assert response.status_code == 200
    mock_service.update_user.assert_called_once()

@patch("app.domains.users.router.UserService")
@patch("app.domains.users.router.UserRepository")
def test_change_password(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.change_password = AsyncMock()
    
    payload = {"current_password": "old", "new_password": "new"}
    response = client.post("/users/me/password", json=payload)
    assert response.status_code == 200
    mock_service.change_password.assert_called_once()

@patch("app.domains.users.router.UserService")
@patch("app.domains.users.router.UserRepository")
def test_soft_delete(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.soft_delete_user = AsyncMock()
    
    response = client.delete("/users/emp-1/soft")
    assert response.status_code == 200
    mock_service.soft_delete_user.assert_called_once_with("emp-1", "company-1")

@patch("app.domains.users.router.UserService")
@patch("app.domains.users.router.UserRepository")
def test_hard_delete(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.hard_delete_user = AsyncMock()
    
    response = client.delete("/users/emp-1/hard")
    assert response.status_code == 200
    mock_service.hard_delete_user.assert_called_once_with("emp-1", "company-1")
