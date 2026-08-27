"""`GET /root/users/insights` -- root konsolunun zengin kullanıcı-istatistik
dökümü. Repo ve Prometheus istemcisi mock'lanır; buradaki test yalnızca
endpoint'in bileşim/şekil sözleşmesini korur."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependency import get_current_user
from app.api.exceptions import BaseAppException, app_exception_handler
from app.core.enums.user_role import UserRole
from app.domains.companies.root_router import router
from app.domains.users.model.user_model import UserModel
from app.infrastructure.database.session import get_db

app = FastAPI()
app.add_exception_handler(BaseAppException, app_exception_handler)
app.include_router(router)


async def _mock_db():
    yield AsyncMock()


def _user(role: UserRole) -> UserModel:
    return UserModel(
        id=f"{role.value}-1",
        company_id="c1",
        username=role.value,
        email=f"{role.value}@example.test",
        role=role.value,
        clearance_level="hizmete_ozel",
        is_active=True,
        is_deleted=False,
        hashed_password="pw",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


app.dependency_overrides[get_db] = _mock_db
client = TestClient(app)


def _repo_stub() -> AsyncMock:
    repo = AsyncMock()
    repo.users_by_role = AsyncMock(return_value=[("employee", 8), ("admin", 2)])
    repo.active_user_count = AsyncMock(side_effect=[3, 6])  # 7d, 30d
    repo.new_user_count = AsyncMock(side_effect=[1, 4])  # 7d, 30d
    repo.run_status_totals = AsyncMock(return_value=[("completed", 40), ("failed", 5)])
    repo.company_rollup = AsyncMock(
        return_value=[
            {"company_id": "c1", "name": "Kurum A", "slug": "a", "is_active": True,
             "user_count": 7, "document_count": 0, "draft_count": 0},
        ]
    )
    repo.daily_activity = AsyncMock(return_value=[{"date": "2026-08-27", "active_users": 3, "runs": 12}])
    repo.top_users = AsyncMock(return_value=[{"username": "employee", "run_count": 84}])
    repo.runs_by_intent = AsyncMock(return_value=[("draft", 56), ("assist", 70)])
    repo.guardrail_by_decision = AsyncMock(return_value=[("passed", 19), ("redacted", 7)])
    return repo


def test_root_gets_the_full_insights_shape():
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.ROOT)
    repo = _repo_stub()
    with patch("app.domains.companies.root_router.RootRepository", return_value=repo), patch(
        "app.domains.companies.root_router.llm_token_usage",
        AsyncMock(return_value={"by_agent": {"writer": 100}, "by_kind": {"output": 100},
                                "total": 100, "available": True}),
    ):
        response = client.get("/root/users/insights")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["kpis"]["total_users"] == 10
    assert data["kpis"]["active_7d"] == 3 and data["kpis"]["active_30d"] == 6
    assert data["kpis"]["activity_rate_30d"] == 0.6
    assert data["kpis"]["new_7d"] == 1 and data["kpis"]["new_30d"] == 4
    assert data["by_role"] == {"employee": 8, "admin": 2}
    assert data["daily_activity"][0]["runs"] == 12
    assert data["runs_by_intent"] == {"draft": 56, "assist": 70}
    assert data["runs_by_status"] == {"completed": 40, "failed": 5}
    assert data["guardrail_by_decision"] == {"passed": 19, "redacted": 7}
    assert data["token_usage"]["by_agent"] == {"writer": 100}
    assert data["seats_by_company"][0]["user_count"] == 7


def test_a_manager_is_refused():
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.MANAGER)
    response = client.get("/root/users/insights")
    assert response.status_code == 403


def test_token_usage_stays_optional_when_prometheus_is_down():
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.ROOT)
    with patch("app.domains.companies.root_router.RootRepository", return_value=_repo_stub()), patch(
        "app.domains.companies.root_router.llm_token_usage",
        AsyncMock(return_value={"by_agent": {}, "by_kind": {}, "total": 0, "available": False}),
    ):
        response = client.get("/root/users/insights")

    assert response.status_code == 200
    assert response.json()["data"]["token_usage"]["available"] is False
