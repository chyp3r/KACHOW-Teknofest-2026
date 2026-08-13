"""API tests for the human-in-the-loop resume endpoints.

/chat/resume(/sync) is how a paused run (missing-information question or a
draft-approval gate) continues; /sessions/{id}/state is how a client that
reloaded mid-pause recovers the pending interrupt instead of losing it.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependency import get_chat_service, require_auth_if_enabled
from app.core.enums.user_role import UserRole
from app.domains.chat.schema.chat_schema import ChatMessageResponse
from app.domains.users.model.user_model import UserModel
from app.main import app

RESUME_SYNC_ENDPOINT = "/api/v1/chat/resume/sync"
RESUME_STREAM_ENDPOINT = "/api/v1/chat/resume"
STATE_ENDPOINT = "/api/v1/chat/sessions/{session_id}/state"

client = TestClient(app, raise_server_exceptions=False)

_CURRENT_USER = UserModel(
    id="user-1",
    company_id="company-1",
    username="user1",
    email="u1@example.com",
    role=UserRole.EMPLOYEE.value,
    clearance_level="hizmete_ozel",
    is_active=True,
    is_deleted=False,
    hashed_password="pw",
    created_at=datetime.now(timezone.utc),
    updated_at=datetime.now(timezone.utc),
)


def _override(service):
    app.dependency_overrides[get_chat_service] = lambda: service
    app.dependency_overrides[require_auth_if_enabled] = lambda: _CURRENT_USER


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_resume_sync_returns_the_completed_response():
    service = AsyncMock()
    service.resume.return_value = ChatMessageResponse(
        reply="Taslağınız onaylandı.", workflow_status="COMPLETED", session_id="s1",
    )
    _override(service)

    response = client.post(
        RESUME_SYNC_ENDPOINT,
        json={"session_id": "s1", "action": "approve"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["workflow_status"] == "COMPLETED"
    assert body["data"]["session_id"] == "s1"
    service.resume.assert_awaited_once()
    call = service.resume.await_args
    assert call.args[0] == "s1"


def test_resume_sync_answer_action_passes_the_answers_through():
    service = AsyncMock()
    service.resume.return_value = ChatMessageResponse(
        reply="Tamamlandı.", workflow_status="COMPLETED", session_id="s1",
    )
    _override(service)

    client.post(
        RESUME_SYNC_ENDPOINT,
        json={"session_id": "s1", "action": "answer", "answers": {"muhatap": "İlgili Makama"}},
    )

    request_arg = service.resume.await_args.args[1]
    assert request_arg.answers == {"muhatap": "İlgili Makama"}
    assert request_arg.action == "answer"


def test_resume_sync_rejects_an_unknown_action():
    service = AsyncMock()
    _override(service)

    response = client.post(
        RESUME_SYNC_ENDPOINT, json={"session_id": "s1", "action": "cancel"}
    )

    assert response.status_code == 422
    service.resume.assert_not_called()


def test_resume_sync_requires_a_session_id():
    service = AsyncMock()
    _override(service)

    response = client.post(RESUME_SYNC_ENDPOINT, json={"action": "approve"})

    assert response.status_code == 422
    service.resume.assert_not_called()


def test_resume_stream_returns_an_sse_response():
    service = AsyncMock()

    async def _events():
        yield {"event": "session", "thread_id": "s1"}
        yield {"event": "final_result", "reply": "Tamam.", "workflow_status": "COMPLETED"}

    # resume_stream() is an async generator function, called but never
    # awaited by the router (it hands the generator straight to _sse_response
    # for `async for`) -- a plain AsyncMock attribute would instead wrap the
    # generator in a coroutine, so this must be a synchronous callable.
    service.resume_stream = MagicMock(return_value=_events())
    _override(service)

    response = client.post(
        RESUME_STREAM_ENDPOINT, json={"session_id": "user-1:s1", "action": "approve"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"event": "final_result"' in response.text
    assert response.text.strip().endswith("data: [DONE]")


# ==========================================
# Session state
# ==========================================
def test_session_state_reports_idle_by_default():
    service = AsyncMock()
    service.get_session_state.return_value = {"status": "idle", "interrupt": None}
    _override(service)

    response = client.get(STATE_ENDPOINT.format(session_id="s1"))

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "idle"


def test_session_state_surfaces_a_pending_interrupt():
    service = AsyncMock()
    service.get_session_state.return_value = {
        "status": "interrupted",
        "interrupt": {"kind": "missing_information", "questions": [{"key": "muhatap"}]},
    }
    _override(service)

    response = client.get(STATE_ENDPOINT.format(session_id="s1"))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "interrupted"
    assert data["interrupt"]["kind"] == "missing_information"
