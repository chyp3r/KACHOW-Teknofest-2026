"""Faz 5 proof: user B cannot reach user A's document_id or session_id.

Before this phase, /chat and /documents had no ownership concept at all --
any caller who knew or guessed a storage_path or session_id could read
another user's document or resume/inspect another user's paused chat
(the architecture migration's B8 finding). These tests exercise the actual
HTTP layer (dependency_overrides standing in for a real JWT, same pattern as
tests/unit/domains/test_user_router.py) rather than the service layer, since
the check is wired at the router boundary.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependency import (
    get_chat_service,
    get_document_analysis_service,
    get_document_repository,
    require_auth_if_enabled,
)
from app.domains.chat.chat_service import ChatService
from app.domains.documents.model.document_model import DocumentModel
from app.domains.users.model.user_model import UserModel
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def _user(user_id: str, role: str = "employee") -> UserModel:
    return UserModel(
        id=user_id,
        username=user_id,
        email=f"{user_id}@example.com",
        role=role,
        clearance_level="hizmete_ozel",
        is_active=True,
        is_deleted=False,
        hashed_password="pw",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# ==========================================
# /chat -- document_id ownership
# ==========================================
def test_chat_message_refuses_a_document_id_owned_by_another_user():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-b")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        id="uploads/a-owns-this.pdf", owner_id="user-a", file_name="a.pdf"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    chat_service = AsyncMock()
    app.dependency_overrides[get_chat_service] = lambda: chat_service

    response = client.post(
        "/api/v1/chat/message",
        json={"message": "Bu evrakta ne yazıyor?", "document_id": "uploads/a-owns-this.pdf"},
    )

    assert response.status_code == 403
    chat_service.handle_message.assert_not_called()
    document_repository.get_by_id.assert_awaited_once_with("uploads/a-owns-this.pdf")


def test_chat_message_allows_a_document_id_the_caller_owns():
    from app.domains.chat.schema.chat_schema import ChatMessageResponse

    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-a")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        id="uploads/mine.pdf", owner_id="user-a", file_name="mine.pdf"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    chat_service = AsyncMock()
    chat_service.handle_message.return_value = ChatMessageResponse(
        reply="İşte özet.", workflow_status="COMPLETED", session_id="user-a:s1"
    )
    app.dependency_overrides[get_chat_service] = lambda: chat_service

    response = client.post(
        "/api/v1/chat/message",
        json={"message": "Bu evrakta ne yazıyor?", "document_id": "uploads/mine.pdf"},
    )

    assert response.status_code == 200
    chat_service.handle_message.assert_awaited_once()


def test_chat_message_allows_an_admin_to_reach_a_document_it_does_not_own():
    from app.domains.chat.schema.chat_schema import ChatMessageResponse

    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("admin-x", role="admin")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        id="uploads/a-owns-this.pdf", owner_id="user-a", file_name="a.pdf"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    chat_service = AsyncMock()
    chat_service.handle_message.return_value = ChatMessageResponse(
        reply="İşte özet.", workflow_status="COMPLETED", session_id="admin-x:s1"
    )
    app.dependency_overrides[get_chat_service] = lambda: chat_service

    response = client.post(
        "/api/v1/chat/message",
        json={"message": "Bu evrakta ne yazıyor?", "document_id": "uploads/a-owns-this.pdf"},
    )

    assert response.status_code == 200
    chat_service.handle_message.assert_awaited_once()


def test_chat_message_allows_a_manager_to_reach_a_document_it_does_not_own():
    from app.domains.chat.schema.chat_schema import ChatMessageResponse

    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("mgr-x", role="manager")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        id="uploads/a-owns-this.pdf", owner_id="user-a", file_name="a.pdf"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    chat_service = AsyncMock()
    chat_service.handle_message.return_value = ChatMessageResponse(
        reply="İşte özet.", workflow_status="COMPLETED", session_id="mgr-x:s1"
    )
    app.dependency_overrides[get_chat_service] = lambda: chat_service

    response = client.post(
        "/api/v1/chat/message",
        json={"message": "Bu evrakta ne yazıyor?", "document_id": "uploads/a-owns-this.pdf"},
    )

    assert response.status_code == 200
    chat_service.handle_message.assert_awaited_once()


def test_chat_message_skips_the_ownership_check_when_unauthenticated():
    """REQUIRE_AUTH=False (the demo/dev default): require_auth_if_enabled
    resolves to None, and no document is denied on that basis alone."""
    from app.domains.chat.schema.chat_schema import ChatMessageResponse

    document_repository = AsyncMock()
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    chat_service = AsyncMock()
    chat_service.handle_message.return_value = ChatMessageResponse(
        reply="Tamam.", workflow_status="COMPLETED", session_id="s1"
    )
    app.dependency_overrides[get_chat_service] = lambda: chat_service

    response = client.post(
        "/api/v1/chat/message",
        json={"message": "Bu evrakta ne yazıyor?", "document_id": "uploads/anything.pdf"},
    )

    assert response.status_code == 200
    document_repository.get_by_id.assert_not_called()


# ==========================================
# /chat -- session_id (thread) ownership
#
# The ownership check for resume/sync and session-state lives inside
# ChatService itself (see _verify_thread_ownership), not the router --
# so these use the real service (with only the planning_graph mocked,
# same fixture shape as tests/unit/domains/test_chat.py) rather than a
# fully-mocked ChatService, which would bypass the code under test.
# ==========================================
def test_resume_sync_refuses_a_session_belonging_to_another_user():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-b")
    planning_graph = AsyncMock()
    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        planning_graph=planning_graph
    )

    response = client.post(
        "/api/v1/chat/resume/sync",
        json={"session_id": "user-a:s1", "action": "approve"},
    )

    assert response.status_code == 403
    planning_graph.ainvoke.assert_not_called()


def test_session_state_refuses_a_session_belonging_to_another_user():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-b")
    planning_graph = AsyncMock()
    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        planning_graph=planning_graph
    )

    response = client.get("/api/v1/chat/sessions/user-a:s1/state")

    assert response.status_code == 403
    planning_graph.aget_state.assert_not_called()


# ==========================================
# /documents/{storage_path} -- ownership
# ==========================================
#: Matches storage_path_validator's expected shape (uploads/<32-hex>.<ext>);
#: an arbitrary string like "uploads/mine.pdf" is rejected at 400 before the
#: ownership check ever runs.
_STORAGE_PATH = f"uploads/{'a' * 32}.pdf"


def test_get_document_analysis_refuses_a_document_owned_by_another_user():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-b")
    document_repository = AsyncMock()
    document_repository.is_owned_by.return_value = False
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = AsyncMock()
    app.dependency_overrides[get_document_analysis_service] = lambda: service

    response = client.get(f"/api/v1/documents/{_STORAGE_PATH}")

    assert response.status_code == 403
    service.get_cached_analysis.assert_not_called()


def test_get_document_analysis_allows_the_owner():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-a")
    document_repository = AsyncMock()
    document_repository.is_owned_by.return_value = True
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = AsyncMock()
    service.get_cached_analysis.return_value = None
    app.dependency_overrides[get_document_analysis_service] = lambda: service

    response = client.get(f"/api/v1/documents/{_STORAGE_PATH}")

    # 404 (no cached analysis in this stub), not 403 -- the ownership check
    # let it through to the actual lookup.
    assert response.status_code == 404
    service.get_cached_analysis.assert_awaited_once()


def test_get_document_analysis_allows_an_admin_that_does_not_own_it():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("admin-x", role="admin")
    document_repository = AsyncMock()
    document_repository.is_owned_by.return_value = False
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = AsyncMock()
    service.get_cached_analysis.return_value = None
    app.dependency_overrides[get_document_analysis_service] = lambda: service

    response = client.get(f"/api/v1/documents/{_STORAGE_PATH}")

    # 404 (no cached analysis in this stub), not 403 -- bypasses_ownership let
    # it through without ever calling is_owned_by.
    assert response.status_code == 404
    document_repository.is_owned_by.assert_not_called()
    service.get_cached_analysis.assert_awaited_once()


def test_get_document_analysis_allows_a_manager_that_does_not_own_it():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("mgr-x", role="manager")
    document_repository = AsyncMock()
    document_repository.is_owned_by.return_value = False
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = AsyncMock()
    service.get_cached_analysis.return_value = None
    app.dependency_overrides[get_document_analysis_service] = lambda: service

    response = client.get(f"/api/v1/documents/{_STORAGE_PATH}")

    assert response.status_code == 404
    document_repository.is_owned_by.assert_not_called()
    service.get_cached_analysis.assert_awaited_once()


def test_list_documents_scopes_to_the_authenticated_owner():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-a")
    document_repository = AsyncMock()
    document_repository.list_for_owner.return_value = []
    document_repository.count_for_owner.return_value = 0
    app.dependency_overrides[get_document_repository] = lambda: document_repository

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    document_repository.list_for_owner.assert_awaited_once()
    assert document_repository.list_for_owner.await_args.args[0] == "user-a"


def test_list_documents_lists_everything_for_an_admin():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("admin-x", role="admin")
    document_repository = AsyncMock()
    document_repository.list_for_owner.return_value = []
    document_repository.count_for_owner.return_value = 0
    app.dependency_overrides[get_document_repository] = lambda: document_repository

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    assert document_repository.list_for_owner.await_args.args[0] is None


def test_list_documents_lists_everything_for_a_manager():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("mgr-x", role="manager")
    document_repository = AsyncMock()
    document_repository.list_for_owner.return_value = []
    document_repository.count_for_owner.return_value = 0
    app.dependency_overrides[get_document_repository] = lambda: document_repository

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    assert document_repository.list_for_owner.await_args.args[0] is None


def test_list_documents_lists_everything_when_unauthenticated():
    document_repository = AsyncMock()
    document_repository.list_for_owner.return_value = []
    document_repository.count_for_owner.return_value = 0
    app.dependency_overrides[get_document_repository] = lambda: document_repository

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    assert document_repository.list_for_owner.await_args.args[0] is None
