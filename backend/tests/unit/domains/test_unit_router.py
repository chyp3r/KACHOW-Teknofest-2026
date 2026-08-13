import pytest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from app.domains.units.router import router
from app.domains.units.model.unit_model import UnitModel
from app.api.dependency import get_current_user, require_roles, require_auth_if_enabled, get_db
from app.domains.users.model.user_model import UserModel
from app.core.enums.user_role import UserRole
from app.api.exceptions import BaseAppException, app_exception_handler

app = FastAPI()
app.add_exception_handler(BaseAppException, app_exception_handler)
app.include_router(router)


async def mock_get_db():
    yield AsyncMock()


def mock_get_current_user_admin():
    return UserModel(
        id="admin-1", company_id="company-1", username="admin", email="a@a.com",
        role=UserRole.ADMIN.value,
        clearance_level="hizmete_ozel", is_active=True, is_deleted=False, hashed_password="pw",
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )


def mock_get_current_user_employee():
    return UserModel(
        id="emp-1", company_id="company-1", username="emp1", email="e@e.com",
        role=UserRole.EMPLOYEE.value,
        clearance_level="hizmete_ozel", is_active=True, is_deleted=False, hashed_password="pw",
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )


def mock_require_roles_admin():
    def role_checker():
        return mock_get_current_user_admin()
    return role_checker


app.dependency_overrides[get_db] = mock_get_db
app.dependency_overrides[require_auth_if_enabled] = mock_get_current_user_admin
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


def _unit(**overrides):
    fields = dict(id="u1", name="Mali İşler", description="Bütçe ve ödemeler.", is_active=True)
    fields.update(overrides)
    return UnitModel(**fields)


@patch("app.domains.units.router.UnitService")
@patch("app.domains.units.router.UnitRepository")
def test_list_units(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.list_units = AsyncMock(return_value=[_unit(), _unit(id="u2", name="Destek Hizmetleri")])

    response = client.get("/units")

    assert response.status_code == 200
    assert len(response.json()["data"]) == 2


@patch("app.domains.units.router.UnitService")
@patch("app.domains.units.router.UnitRepository")
def test_create_unit_as_admin(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.create_unit = AsyncMock(return_value=_unit())

    payload = {"name": "Mali İşler", "description": "Bütçe ve ödemeler."}
    response = client.post("/units", json=payload)

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Mali İşler"
    mock_service.create_unit.assert_called_once()


@patch("app.domains.units.router.UnitService")
@patch("app.domains.units.router.UnitRepository")
def test_create_unit_as_employee_forbidden(mock_repo_cls, mock_service_cls, override_as_employee):
    payload = {"name": "Mali İşler", "description": "Bütçe ve ödemeler."}
    response = client.post("/units", json=payload)
    assert response.status_code == 403


@patch("app.domains.units.router.UnitService")
@patch("app.domains.units.router.UnitRepository")
def test_update_unit_as_admin(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.update_unit = AsyncMock(return_value=_unit(description="Güncellendi"))

    response = client.patch("/units/u1", json={"description": "Güncellendi"})

    assert response.status_code == 200
    assert response.json()["data"]["description"] == "Güncellendi"
    mock_service.update_unit.assert_called_once()


@patch("app.domains.units.router.UnitService")
@patch("app.domains.units.router.UnitRepository")
def test_update_unit_as_employee_forbidden(mock_repo_cls, mock_service_cls, override_as_employee):
    response = client.patch("/units/u1", json={"description": "x"})
    assert response.status_code == 403


@patch("app.domains.units.router.UnitService")
@patch("app.domains.units.router.UnitRepository")
def test_delete_unit_as_admin(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.delete_unit = AsyncMock()

    response = client.delete("/units/u1")

    assert response.status_code == 200
    mock_service.delete_unit.assert_called_once_with("u1", "company-1")


@patch("app.domains.units.router.UnitService")
@patch("app.domains.units.router.UnitRepository")
def test_delete_unit_as_employee_forbidden(mock_repo_cls, mock_service_cls, override_as_employee):
    response = client.delete("/units/u1")
    assert response.status_code == 403
