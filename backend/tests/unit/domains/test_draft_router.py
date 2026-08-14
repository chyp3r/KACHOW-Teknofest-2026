"""HTTP-level tests for app.domains.drafts.router.

Regression coverage for a real bug found via live smoke testing: the Faz 2
ABAC refactor (`_assert_owns_draft`) removed `drafts/router.py`'s import of
`bypasses_ownership`, but `list_drafts` still called it directly -- a
`NameError` on every real `GET /drafts` request that no existing test
caught, because nothing exercised this router at the HTTP level (only
`app.domains.drafts.service.DraftService`/`DraftRepository` had unit tests,
both of which mock past the router entirely). Same standalone-app +
dependency_overrides pattern as test_user_router.py/
test_permission_grant_router.py.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependency import get_draft_history_service, require_auth_if_enabled
from app.api.exceptions import BaseAppException, app_exception_handler
from app.core.enums.user_role import UserRole
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.router import router
from app.domains.users.model.user_model import UserModel

app = FastAPI()
app.add_exception_handler(BaseAppException, app_exception_handler)
app.include_router(router)


def _user(user_id: str = "emp-1", role: UserRole = UserRole.EMPLOYEE, company_id: str = "company-1") -> UserModel:
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


def _draft(**overrides) -> DraftModel:
    fields = dict(
        id="draft-1", company_id="company-1", user_id="emp-1", session_id=None,
        document_id=None, version=1, content="içerik", is_deleted=False,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return DraftModel(**fields)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


def test_list_drafts_succeeds_for_an_employee():
    """The actual regression case: GET /drafts must not 500."""
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user()
    service = AsyncMock()
    service.list_drafts.return_value = [_draft()]
    service.count_drafts.return_value = 1
    app.dependency_overrides[get_draft_history_service] = lambda: service

    response = client.get("/drafts")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["total"] == 1
    service.list_drafts.assert_awaited_once()
    call_kwargs = service.list_drafts.await_args.kwargs
    assert call_kwargs["company_id"] == "company-1"
    assert call_kwargs["user_id"] == "emp-1"


def test_list_drafts_scopes_to_the_whole_company_for_a_manager():
    """bypasses_ownership(MANAGER) => user_id=None, company-wide listing."""
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user(role=UserRole.MANAGER)
    service = AsyncMock()
    service.list_drafts.return_value = []
    service.count_drafts.return_value = 0
    app.dependency_overrides[get_draft_history_service] = lambda: service

    response = client.get("/drafts")

    assert response.status_code == 200
    call_kwargs = service.list_drafts.await_args.kwargs
    assert call_kwargs["user_id"] is None
    assert call_kwargs["company_id"] == "company-1"


def test_get_draft_allows_the_owner():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user(user_id="emp-1")
    service = AsyncMock()
    service.get_draft.return_value = _draft(user_id="emp-1")
    app.dependency_overrides[get_draft_history_service] = lambda: service

    response = client.get("/drafts/draft-1")

    assert response.status_code == 200


def test_get_draft_refuses_a_non_owner_employee():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user(user_id="emp-2")
    service = AsyncMock()
    service.get_draft.return_value = _draft(user_id="emp-1")
    app.dependency_overrides[get_draft_history_service] = lambda: service

    response = client.get("/drafts/draft-1")

    assert response.status_code == 403


def test_get_draft_allows_an_admin_that_does_not_own_it():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user(user_id="admin-1", role=UserRole.ADMIN)
    service = AsyncMock()
    service.get_draft.return_value = _draft(user_id="emp-1")
    app.dependency_overrides[get_draft_history_service] = lambda: service

    response = client.get("/drafts/draft-1")

    assert response.status_code == 200


def test_delete_draft_refuses_a_non_owner_employee():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user(user_id="emp-2")
    service = AsyncMock()
    service.get_draft.return_value = _draft(user_id="emp-1")
    app.dependency_overrides[get_draft_history_service] = lambda: service

    response = client.delete("/drafts/draft-1")

    assert response.status_code == 403
    service.delete_draft.assert_not_awaited()
