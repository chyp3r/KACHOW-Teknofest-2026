from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependency import get_current_user, get_db
from app.api.exceptions import BaseAppException, app_exception_handler
from app.core.enums.user_role import UserRole
from app.domains.training.model.training_run_model import TrainingRunModel
from app.domains.training.model.training_sample_model import TrainingSampleModel
from app.domains.training.router import company_router, router
from app.domains.users.model.user_model import UserModel

app = FastAPI()
app.add_exception_handler(BaseAppException, app_exception_handler)
app.include_router(router)
app.include_router(company_router)


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
MANAGER_USER = _user("manager-1", UserRole.MANAGER.value, "company-1")
OTHER_ADMIN_USER = _user("admin-2", UserRole.ADMIN.value, "company-2")

app.dependency_overrides[get_db] = mock_get_db
app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_current_user():
    yield
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER


def _sample(**overrides) -> TrainingSampleModel:
    fields = dict(
        id="sample-1", company_id="company-1", training_run_id=None, source="explicit_feedback",
        source_feedback_id="fb-1", source_draft_id="draft-1", prompt_context="", chosen="Sayın Makam,",
        rejected=None, weight=1.0, pair_hash="hash-1", used_in_runs=None, is_deleted=False,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return TrainingSampleModel(**fields)


def _run(**overrides) -> TrainingRunModel:
    fields = dict(
        id="run-1", company_id="company-1", kind="style_adapter", status="succeeded",
        triggered_by="admin-1", trigger="manual", sample_count=60,
        metrics={"adapter_version": 2}, error=None, started_at=None, finished_at=None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return TrainingRunModel(**fields)


# ==========================================
# compile
# ==========================================
@patch("app.domains.training.router.TrainingService")
@patch("app.domains.training.router.TrainingRepository")
def test_compile_as_own_admin(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.compile_samples = AsyncMock(return_value=[_sample()])

    response = client.post("/companies/company-1/training-samples/compile")

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1


@patch("app.domains.training.router.TrainingService")
@patch("app.domains.training.router.TrainingRepository")
def test_compile_as_a_different_companys_admin_forbidden(mock_repo_cls, mock_service_cls):
    app.dependency_overrides[get_current_user] = lambda: OTHER_ADMIN_USER
    mock_service = mock_service_cls.return_value
    mock_service.compile_samples = AsyncMock(return_value=[])

    response = client.post("/companies/company-1/training-samples/compile")

    assert response.status_code == 403
    mock_service.compile_samples.assert_not_awaited()


@patch("app.domains.training.router.TrainingService")
@patch("app.domains.training.router.TrainingRepository")
def test_compile_as_manager_forbidden(mock_repo_cls, mock_service_cls):
    """Compiling/training is Root/Admin-only, unlike list/stats -- Manager
    can read, not trigger."""
    app.dependency_overrides[get_current_user] = lambda: MANAGER_USER

    response = client.post("/companies/company-1/training-samples/compile")

    assert response.status_code == 403


# ==========================================
# list / stats / export
# ==========================================
@patch("app.domains.training.router.TrainingService")
@patch("app.domains.training.router.TrainingRepository")
def test_list_samples_as_manager(mock_repo_cls, mock_service_cls):
    app.dependency_overrides[get_current_user] = lambda: MANAGER_USER
    mock_service = mock_service_cls.return_value
    mock_service.list_samples = AsyncMock(return_value=[_sample()])
    mock_service.count_samples = AsyncMock(return_value=1)

    response = client.get("/companies/company-1/training-samples")

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1


@patch("app.domains.training.router.TrainingService")
@patch("app.domains.training.router.TrainingRepository")
def test_stats_as_own_admin(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.stats = AsyncMock(
        return_value={
            "total": 12, "by_source": {"explicit_feedback": 12},
            "min_samples_required": 50, "samples_remaining_to_threshold": 38,
        }
    )

    response = client.get("/companies/company-1/training-samples/stats")

    assert response.status_code == 200
    assert response.json()["data"]["samples_remaining_to_threshold"] == 38


@patch("app.domains.training.router.TrainingService")
@patch("app.domains.training.router.TrainingRepository")
def test_export_returns_jsonl_content(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.export_samples = AsyncMock(
        return_value=[_sample(chosen="Sayın Makam, arz ederim.", rejected=None)]
    )

    response = client.get("/companies/company-1/training-samples/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert "Sayın Makam, arz ederim." in response.text


# ==========================================
# delete
# ==========================================
@patch("app.domains.training.router.TrainingService")
@patch("app.domains.training.router.TrainingRepository")
def test_delete_sample_as_own_admin(mock_repo_cls, mock_service_cls):
    mock_service = mock_service_cls.return_value
    mock_service.delete_sample = AsyncMock(return_value=_sample())

    response = client.delete("/training-samples/sample-1")

    assert response.status_code == 200
    assert response.json()["data"]["deleted"] is True


@patch("app.domains.training.router.TrainingService")
@patch("app.domains.training.router.TrainingRepository")
def test_delete_sample_as_manager_forbidden(mock_repo_cls, mock_service_cls):
    app.dependency_overrides[get_current_user] = lambda: MANAGER_USER

    response = client.delete("/training-samples/sample-1")

    assert response.status_code == 403


# ==========================================
# training runs (quota-gated)
# ==========================================
@patch("app.domains.training.router.get_fast_llm_client")
@patch("app.domains.training.router.TrainingService")
@patch("app.domains.training.router.TrainingRepository")
@patch("app.domains.training.router.QuotaService")
def test_trigger_training_run_as_own_admin(
    mock_quota_cls, mock_repo_cls, mock_service_cls, mock_llm
):
    mock_quota = mock_quota_cls.return_value
    mock_quota.check_and_increment = AsyncMock(return_value=None)
    mock_service = mock_service_cls.return_value
    mock_service.run_style_adapter_training = AsyncMock(return_value=_run())

    response = client.post("/companies/company-1/training-runs")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "succeeded"
    mock_quota.check_and_increment.assert_awaited_once()


@patch("app.domains.training.router.get_fast_llm_client")
@patch("app.domains.training.router.TrainingService")
@patch("app.domains.training.router.TrainingRepository")
@patch("app.domains.training.router.QuotaService")
def test_trigger_training_run_blocked_by_quota(
    mock_quota_cls, mock_repo_cls, mock_service_cls, mock_llm
):
    from app.api.exceptions.rate_limit import RateLimitException

    mock_quota = mock_quota_cls.return_value
    mock_quota.check_and_increment = AsyncMock(
        side_effect=RateLimitException(message="Bu ay için training_runs kotası doldu.")
    )
    mock_service = mock_service_cls.return_value
    mock_service.run_style_adapter_training = AsyncMock(return_value=_run())

    response = client.post("/companies/company-1/training-runs")

    assert response.status_code == 429
    mock_service.run_style_adapter_training.assert_not_awaited()


@patch("app.domains.training.router.get_fast_llm_client")
@patch("app.domains.training.router.TrainingService")
@patch("app.domains.training.router.TrainingRepository")
@patch("app.domains.training.router.QuotaService")
def test_trigger_training_run_as_manager_forbidden(
    mock_quota_cls, mock_repo_cls, mock_service_cls, mock_llm
):
    app.dependency_overrides[get_current_user] = lambda: MANAGER_USER

    response = client.post("/companies/company-1/training-runs")

    assert response.status_code == 403


@patch("app.domains.training.router.TrainingService")
@patch("app.domains.training.router.TrainingRepository")
def test_list_runs_as_manager(mock_repo_cls, mock_service_cls):
    app.dependency_overrides[get_current_user] = lambda: MANAGER_USER
    mock_service = mock_service_cls.return_value
    mock_service.list_runs = AsyncMock(return_value=[_run()])
    mock_service.count_runs = AsyncMock(return_value=1)

    response = client.get("/companies/company-1/training-runs")

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
