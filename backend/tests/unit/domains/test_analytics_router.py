from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependency import get_current_user
from app.api.exceptions import BaseAppException, app_exception_handler
from app.core.enums.user_role import UserRole
from app.domains.analytics.router import router
from app.domains.users.model.user_model import UserModel
from app.infrastructure.database.session import get_db


app = FastAPI()
app.add_exception_handler(BaseAppException, app_exception_handler)
app.include_router(router)


async def mock_get_db():
    yield AsyncMock()


def _user(user_id: str, role: UserRole) -> UserModel:
    return UserModel(
        id=user_id,
        company_id="company-1",
        username=user_id,
        email=f"{user_id}@example.test",
        role=role.value,
        clearance_level="hizmete_ozel",
        is_active=True,
        is_deleted=False,
        hashed_password="pw",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


ADMIN_USER = _user("admin-1", UserRole.ADMIN)
MANAGER_USER = _user("manager-1", UserRole.MANAGER)

app.dependency_overrides[get_db] = mock_get_db
app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_current_user():
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    yield


def test_observability_links_reject_manager():
    app.dependency_overrides[get_current_user] = lambda: MANAGER_USER

    response = client.get("/companies/company-1/analytics/links")

    assert response.status_code == 403


@patch("app.domains.analytics.router.CompanyRepository")
def test_observability_links_allow_company_admin(mock_company_repository):
    mock_company_repository.return_value.get_by_id = AsyncMock(
        return_value=SimpleNamespace(slug="company-one")
    )

    response = client.get("/companies/company-1/analytics/links")

    assert response.status_code == 200
    assert "var-company=company-one" in response.json()["data"]["grafana_url"]
