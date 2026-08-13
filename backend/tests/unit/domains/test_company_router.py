import pytest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from app.domains.companies.router import router
from app.domains.companies.model.company_model import CompanyModel
from app.api.dependency import get_current_user, get_db
from app.domains.users.model.user_model import UserModel
from app.core.enums.user_role import UserRole
from app.api.exceptions import BaseAppException, app_exception_handler

app = FastAPI()
app.add_exception_handler(BaseAppException, app_exception_handler)
app.include_router(router)


async def mock_get_db():
    yield AsyncMock()


def _user(user_id: str, role: str, company_id) -> UserModel:
    return UserModel(
        id=user_id, company_id=company_id, username=user_id, email=f"{user_id}@e.com", role=role,
        clearance_level="cok_gizli", is_active=True, is_deleted=False, hashed_password="pw",
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )


ROOT_USER = _user("root-1", UserRole.ROOT.value, None)
ADMIN_USER = _user("admin-1", UserRole.ADMIN.value, "company-1")
OTHER_ADMIN_USER = _user("admin-2", UserRole.ADMIN.value, "company-2")

app.dependency_overrides[get_db] = mock_get_db
app.dependency_overrides[get_current_user] = lambda: ROOT_USER

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_current_user():
    """require_roles / require_auth_if_enabled both resolve down to
    get_current_user (see app.api.dependency) -- overriding the current
    user here is what actually drives every role check below, not a
    separate require_roles override (its own closures still call the real
    get_current_user internally)."""
    yield
    app.dependency_overrides[get_current_user] = lambda: ROOT_USER


def _company(**overrides):
    fields = dict(id="company-1", name="Acme Holding", slug="acme", is_active=True, settings={})
    fields.update(overrides)
    return CompanyModel(**fields)


@patch("app.domains.companies.router.CompanyService")
@patch("app.domains.companies.router.CompanyRepository")
@patch("app.domains.companies.router.UserRepository")
def test_create_company_as_root(mock_user_repo_cls, mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.create_company = AsyncMock(return_value=_company())

    payload = {"name": "Acme Holding", "slug": "acme"}
    response = client.post("/companies", json=payload)

    assert response.status_code == 200
    assert response.json()["data"]["slug"] == "acme"
    mock_service.create_company.assert_called_once()


@patch("app.domains.companies.router.CompanyService")
@patch("app.domains.companies.router.CompanyRepository")
@patch("app.domains.companies.router.UserRepository")
def test_create_company_as_admin_forbidden(mock_user_repo_cls, mock_repo_cls, mock_service_cls):
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    response = client.post("/companies", json={"name": "Acme", "slug": "acme"})

    assert response.status_code == 403


@patch("app.domains.companies.router.CompanyService")
@patch("app.domains.companies.router.CompanyRepository")
@patch("app.domains.companies.router.UserRepository")
def test_list_companies_as_root(mock_user_repo_cls, mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.list_companies = AsyncMock(return_value=([_company()], 1))

    response = client.get("/companies?page=1&size=20")

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
    assert len(response.json()["data"]["items"]) == 1


@patch("app.domains.companies.router.CompanyService")
@patch("app.domains.companies.router.CompanyRepository")
@patch("app.domains.companies.router.UserRepository")
def test_list_companies_as_admin_forbidden(mock_user_repo_cls, mock_repo_cls, mock_service_cls):
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    response = client.get("/companies")

    assert response.status_code == 403


@patch("app.domains.companies.router.CompanyService")
@patch("app.domains.companies.router.CompanyRepository")
@patch("app.domains.companies.router.UserRepository")
def test_get_company_as_root(mock_user_repo_cls, mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.get_company_by_id = AsyncMock(return_value=_company())

    response = client.get("/companies/company-1")

    assert response.status_code == 200
    assert response.json()["data"]["id"] == "company-1"


@patch("app.domains.companies.router.CompanyService")
@patch("app.domains.companies.router.CompanyRepository")
@patch("app.domains.companies.router.UserRepository")
def test_get_company_as_own_admin(mock_user_repo_cls, mock_repo_cls, mock_service_cls):
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    mock_service = mock_service_cls.return_value
    mock_service.get_company_by_id = AsyncMock(return_value=_company())

    response = client.get("/companies/company-1")

    assert response.status_code == 200


@patch("app.domains.companies.router.CompanyService")
@patch("app.domains.companies.router.CompanyRepository")
@patch("app.domains.companies.router.UserRepository")
def test_get_company_as_a_different_companys_admin_forbidden(
    mock_user_repo_cls, mock_repo_cls, mock_service_cls
):
    app.dependency_overrides[get_current_user] = lambda: OTHER_ADMIN_USER
    mock_service = mock_service_cls.return_value
    mock_service.get_company_by_id = AsyncMock(return_value=_company())

    response = client.get("/companies/company-1")

    assert response.status_code == 403
    mock_service.get_company_by_id.assert_not_called()


@patch("app.domains.companies.router.CompanyService")
@patch("app.domains.companies.router.CompanyRepository")
@patch("app.domains.companies.router.UserRepository")
def test_update_company_as_a_different_companys_admin_forbidden(
    mock_user_repo_cls, mock_repo_cls, mock_service_cls
):
    app.dependency_overrides[get_current_user] = lambda: OTHER_ADMIN_USER

    response = client.patch("/companies/company-1", json={"name": "Hacked"})

    assert response.status_code == 403


@patch("app.domains.companies.router.CompanyService")
@patch("app.domains.companies.router.CompanyRepository")
@patch("app.domains.companies.router.UserRepository")
def test_assign_company_admin_as_root(mock_user_repo_cls, mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_user = _user("user-1", UserRole.ADMIN.value, "company-1")
    mock_service.assign_admin = AsyncMock(return_value=mock_user)

    response = client.post("/companies/company-1/admins", json={"user_id": "user-1"})

    assert response.status_code == 200
    assert response.json()["data"]["role"] == "admin"
    mock_service.assign_admin.assert_called_once_with("company-1", "user-1")


@patch("app.domains.companies.router.CompanyService")
@patch("app.domains.companies.router.CompanyRepository")
@patch("app.domains.companies.router.UserRepository")
def test_assign_company_admin_as_admin_forbidden(mock_user_repo_cls, mock_repo_cls, mock_service_cls):
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    response = client.post("/companies/company-1/admins", json={"user_id": "user-1"})

    assert response.status_code == 403


@patch("app.domains.companies.router.CompanyService")
@patch("app.domains.companies.router.CompanyRepository")
@patch("app.domains.companies.router.UserRepository")
def test_delete_company_as_root(mock_user_repo_cls, mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.delete_company = AsyncMock()

    response = client.delete("/companies/company-1")

    assert response.status_code == 200
    mock_service.delete_company.assert_called_once_with("company-1")


@patch("app.domains.companies.router.CompanyService")
@patch("app.domains.companies.router.CompanyRepository")
@patch("app.domains.companies.router.UserRepository")
def test_delete_company_as_admin_forbidden(mock_user_repo_cls, mock_repo_cls, mock_service_cls):
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    response = client.delete("/companies/company-1")

    assert response.status_code == 403
