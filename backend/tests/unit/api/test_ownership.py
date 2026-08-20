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
    get_draft_repository,
    get_draft_history_service,
    get_draft_service,
    require_auth_if_enabled,
)
from app.domains.chat.chat_service import ChatService
from app.domains.documents.model.document_model import DocumentModel
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.users.model.user_model import UserModel
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def _user(user_id: str, role: str = "employee", company_id: str = "company-1") -> UserModel:
    return UserModel(
        id=user_id,
        company_id=company_id,
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
    app.dependency_overrides[get_draft_repository] = lambda: AsyncMock()
    yield
    app.dependency_overrides.clear()


# ==========================================
# /chat -- document_id ownership
# ==========================================
def test_chat_message_refuses_a_document_id_owned_by_another_user():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-b")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1",
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
    document_repository.get_by_id.assert_awaited_once_with("uploads/a-owns-this.pdf", "company-1")


def test_chat_message_allows_a_document_id_the_caller_owns():
    from app.domains.chat.schema.chat_schema import ChatMessageResponse

    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-a")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1",
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
        company_id="company-1",
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
        company_id="company-1",
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


# ==========================================
# /chat -- draft_id update authorization
# ==========================================
def test_chat_message_refuses_a_draft_owned_by_another_employee():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-b")
    document_repository = AsyncMock()
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    draft_repository = AsyncMock()
    draft_repository.get_by_id.return_value = _draft(user_id="user-a")
    app.dependency_overrides[get_draft_repository] = lambda: draft_repository
    chat_service = AsyncMock()
    app.dependency_overrides[get_chat_service] = lambda: chat_service

    response = client.post(
        "/api/v1/chat/message",
        json={"message": "Üslubu sadeleştir.", "draft_id": "draft-1"},
    )

    assert response.status_code == 403
    chat_service.handle_message.assert_not_called()


def test_chat_message_passes_an_authorized_revision_draft_to_the_service():
    from app.domains.chat.schema.chat_schema import ChatMessageResponse

    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-a")
    document_repository = AsyncMock()
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    draft_repository = AsyncMock()
    draft = _draft(user_id="user-a")
    draft_repository.get_by_id.return_value = draft
    app.dependency_overrides[get_draft_repository] = lambda: draft_repository
    chat_service = AsyncMock()
    chat_service.handle_message.return_value = ChatMessageResponse(
        reply="Taslak revize edildi.", workflow_status="COMPLETED", session_id="user-a:s1"
    )
    app.dependency_overrides[get_chat_service] = lambda: chat_service

    response = client.post(
        "/api/v1/chat/message",
        json={"message": "Üslubu sadeleştir.", "draft_id": "draft-1"},
    )

    assert response.status_code == 200
    assert chat_service.handle_message.await_args.kwargs["revision_draft"] is draft


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
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1", id=_STORAGE_PATH, owner_id="user-a", file_name="gizli.pdf"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = AsyncMock()
    app.dependency_overrides[get_document_analysis_service] = lambda: service

    response = client.get(f"/api/v1/documents/{_STORAGE_PATH}")

    assert response.status_code == 403
    service.get_cached_analysis.assert_not_called()


def test_get_document_analysis_allows_the_owner():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-a")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1", id=_STORAGE_PATH, owner_id="user-a", file_name="mine.pdf"
    )
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
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1", id=_STORAGE_PATH, owner_id="user-a", file_name="gizli.pdf"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = AsyncMock()
    service.get_cached_analysis.return_value = None
    app.dependency_overrides[get_document_analysis_service] = lambda: service

    response = client.get(f"/api/v1/documents/{_STORAGE_PATH}")

    # 404 (no cached analysis in this stub), not 403 -- bypasses_ownership let
    # it through despite the different owner_id.
    assert response.status_code == 404
    service.get_cached_analysis.assert_awaited_once()


def test_get_document_analysis_allows_a_manager_that_does_not_own_it():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("mgr-x", role="manager")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1", id=_STORAGE_PATH, owner_id="user-a", file_name="gizli.pdf"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = AsyncMock()
    service.get_cached_analysis.return_value = None
    app.dependency_overrides[get_document_analysis_service] = lambda: service

    response = client.get(f"/api/v1/documents/{_STORAGE_PATH}")

    assert response.status_code == 404
    service.get_cached_analysis.assert_awaited_once()


# ==========================================
# /documents/draft -- ownership
#
# DraftService reads the source document straight from storage by
# storage_path, with no ownership/clearance concept of its own -- the check
# belongs at the router boundary (see generate_draft's docstring).
# ==========================================
def _draft_request_body() -> dict:
    return {
        "storage_path": _STORAGE_PATH,
        "classification": {"document_type": "petition"},
    }


def _draft_service_stub() -> AsyncMock:
    from app.domains.documents.schema.document_schema import DraftResponseSchema

    service = AsyncMock()
    service.generate_draft_and_route.return_value = DraftResponseSchema(
        draft="İşte taslak.",
        confidence_score=90.0,
        requires_human_approval=False,
        destination="İnsan Kaynakları Daire Başkanlığı",
        justification="Personel izin talebiyle ilgili.",
    )
    return service


def test_generate_draft_refuses_a_document_owned_by_another_user():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-b")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1",
        id=_STORAGE_PATH, owner_id="user-a", file_name="gizli.pdf"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = _draft_service_stub()
    app.dependency_overrides[get_draft_service] = lambda: service

    response = client.post("/api/v1/documents/draft", json=_draft_request_body())

    assert response.status_code == 403
    service.generate_draft_and_route.assert_not_called()


def test_generate_draft_allows_the_owner():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-a")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1",
        id=_STORAGE_PATH, owner_id="user-a", file_name="mine.pdf"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = _draft_service_stub()
    app.dependency_overrides[get_draft_service] = lambda: service

    response = client.post("/api/v1/documents/draft", json=_draft_request_body())

    assert response.status_code == 200
    service.generate_draft_and_route.assert_awaited_once()


def test_generate_draft_refuses_a_document_above_the_callers_clearance():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-a")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1",
        id=_STORAGE_PATH, owner_id="user-a", file_name="mine.pdf", sensitivity_level="gizli"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = _draft_service_stub()
    app.dependency_overrides[get_draft_service] = lambda: service

    response = client.post("/api/v1/documents/draft", json=_draft_request_body())

    assert response.status_code == 403
    service.generate_draft_and_route.assert_not_called()


def test_generate_draft_allows_an_admin_that_does_not_own_it():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("admin-x", role="admin")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1",
        id=_STORAGE_PATH, owner_id="user-a", file_name="gizli.pdf", sensitivity_level="cok_gizli"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = _draft_service_stub()
    app.dependency_overrides[get_draft_service] = lambda: service

    response = client.post("/api/v1/documents/draft", json=_draft_request_body())

    assert response.status_code == 200
    service.generate_draft_and_route.assert_awaited_once()


def test_list_documents_scopes_to_the_authenticated_owner():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-a")
    document_repository = AsyncMock()
    document_repository.list_for_owner.return_value = []
    document_repository.count_for_owner.return_value = 0
    app.dependency_overrides[get_document_repository] = lambda: document_repository

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    document_repository.list_for_owner.assert_awaited_once()
    assert document_repository.list_for_owner.await_args.args == ("company-1", "user-a")


def test_list_documents_lists_everything_for_an_admin():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("admin-x", role="admin")
    document_repository = AsyncMock()
    document_repository.list_for_owner.return_value = []
    document_repository.count_for_owner.return_value = 0
    app.dependency_overrides[get_document_repository] = lambda: document_repository

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    assert document_repository.list_for_owner.await_args.args == ("company-1", None)


def test_list_documents_lists_everything_for_a_manager():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("mgr-x", role="manager")
    document_repository = AsyncMock()
    document_repository.list_for_owner.return_value = []
    document_repository.count_for_owner.return_value = 0
    app.dependency_overrides[get_document_repository] = lambda: document_repository

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    assert document_repository.list_for_owner.await_args.args == ("company-1", None)


# ==========================================
# DELETE /drafts/{draft_id} -- ownership
# ==========================================
def _draft(draft_id: str = "draft-1", user_id: str = "user-a") -> DraftModel:
    return DraftModel(
        id=draft_id,
        user_id=user_id,
        session_id="session-1",
        document_id=None,
        version=1,
        content="İçerik",
        is_deleted=False,
    )


def test_delete_draft_refuses_a_draft_owned_by_another_user():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-b")
    service = AsyncMock()
    service.get_draft.return_value = _draft(user_id="user-a")
    app.dependency_overrides[get_draft_history_service] = lambda: service

    response = client.delete("/api/v1/drafts/draft-1")

    assert response.status_code == 403
    service.delete_draft.assert_not_called()


def test_delete_draft_allows_the_owner():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-a")
    service = AsyncMock()
    service.get_draft.return_value = _draft(user_id="user-a")
    app.dependency_overrides[get_draft_history_service] = lambda: service

    response = client.delete("/api/v1/drafts/draft-1")

    assert response.status_code == 200
    assert response.json()["data"]["deleted"] is True
    service.delete_draft.assert_awaited_once_with("draft-1")


def test_delete_draft_allows_an_admin_that_does_not_own_it():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("admin-x", role="admin")
    service = AsyncMock()
    service.get_draft.return_value = _draft(user_id="user-a")
    app.dependency_overrides[get_draft_history_service] = lambda: service

    response = client.delete("/api/v1/drafts/draft-1")

    assert response.status_code == 200
    service.delete_draft.assert_awaited_once_with("draft-1")


# ==========================================
# DELETE /documents/{storage_path} -- ownership
# ==========================================
def test_delete_document_refuses_a_document_owned_by_another_user():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-b")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1",
        id=_STORAGE_PATH, owner_id="user-a", file_name="gizli.pdf"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = AsyncMock()
    app.dependency_overrides[get_document_analysis_service] = lambda: service

    response = client.delete(f"/api/v1/documents/{_STORAGE_PATH}")

    assert response.status_code == 403
    service.delete_document.assert_not_called()


def test_delete_document_allows_the_owner():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-a")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1",
        id=_STORAGE_PATH, owner_id="user-a", file_name="mine.pdf"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = AsyncMock()
    app.dependency_overrides[get_document_analysis_service] = lambda: service

    response = client.delete(f"/api/v1/documents/{_STORAGE_PATH}")

    assert response.status_code == 200
    assert response.json()["data"]["deleted"] is True
    service.delete_document.assert_awaited_once_with(_STORAGE_PATH, "company-1")


def test_delete_document_refuses_a_document_above_the_callers_clearance():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("user-a")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1",
        id=_STORAGE_PATH, owner_id="user-a", file_name="mine.pdf", sensitivity_level="gizli"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = AsyncMock()
    app.dependency_overrides[get_document_analysis_service] = lambda: service

    response = client.delete(f"/api/v1/documents/{_STORAGE_PATH}")

    assert response.status_code == 403
    service.delete_document.assert_not_called()


def test_delete_document_allows_an_admin_that_does_not_own_it():
    app.dependency_overrides[require_auth_if_enabled] = lambda: _user("admin-x", role="admin")
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = DocumentModel(
        company_id="company-1",
        id=_STORAGE_PATH, owner_id="user-a", file_name="mine.pdf"
    )
    app.dependency_overrides[get_document_repository] = lambda: document_repository
    service = AsyncMock()
    app.dependency_overrides[get_document_analysis_service] = lambda: service

    response = client.delete(f"/api/v1/documents/{_STORAGE_PATH}")

    assert response.status_code == 200
    service.delete_document.assert_awaited_once_with(_STORAGE_PATH, "company-1")
