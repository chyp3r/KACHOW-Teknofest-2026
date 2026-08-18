from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.domains.transfers.artifact_resolution import ArtifactResolutionService
from app.domains.documents.model.document_model import DocumentModel
from app.domains.drafts.model.draft_model import DraftModel


def _draft(**overrides) -> DraftModel:
    fields = dict(
        id="draft-1", company_id="company-1", user_id="emp-1", session_id="thread-1",
        document_id=None, version=1, content="içerik", destination=None,
        destination_unit_id=None, destination_justification=None, correspondence_type=None,
        is_deleted=False, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return DraftModel(**fields)


def _document(**overrides) -> DocumentModel:
    fields = dict(
        id="uploads/doc.pdf", company_id="company-1", owner_id="emp-1", file_name="doc.pdf",
        document_type="", document_type_label="", compliance_status="", summary="",
        sensitivity_level="unmarked", pii_flagged=False,
    )
    fields.update(overrides)
    return DocumentModel(**fields)


@pytest.fixture
def draft_repo():
    return AsyncMock()


@pytest.fixture
def document_repo():
    return AsyncMock()


@pytest.fixture
def service(draft_repo, document_repo):
    return ArtifactResolutionService(draft_repo, document_repo)


@pytest.mark.asyncio
async def test_explicit_draft_id_wins_outright(service, draft_repo):
    explicit = _draft(id="draft-explicit")
    draft_repo.get_by_id.return_value = explicit

    result = await service.resolve_draft(
        company_id="company-1", user_id="emp-1", thread_id="thread-1", explicit_draft_id="draft-explicit"
    )
    assert result.status == "resolved"
    assert result.candidates == (explicit,)
    draft_repo.get_latest_for_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_draft_id_from_a_different_company_falls_through(service, draft_repo):
    """The whole reason `explicit_draft_id` is treated as a hint, never a
    trusted pointer (see SessionFocus.active_draft_id's docstring) -- a
    stale/cross-tenant id must not resolve, and must not error either."""
    draft_repo.get_by_id.return_value = _draft(id="draft-explicit", company_id="other-company")
    draft_repo.get_latest_for_session.return_value = _draft(id="draft-session")

    result = await service.resolve_draft(
        company_id="company-1", user_id="emp-1", thread_id="thread-1", explicit_draft_id="draft-explicit"
    )
    assert result.status == "resolved"
    assert result.candidates[0].id == "draft-session"


@pytest.mark.asyncio
async def test_thread_latest_draft_wins_regardless_of_how_many_idle_turns_passed(service, draft_repo):
    """The user's actual scenario: taslak üret, N alakasız tur, sonra
    "gönder" -- get_latest_for_session is a plain query with no idle-turn
    concept at all, unlike SessionFocus.active_draft."""
    draft_repo.get_latest_for_session.return_value = _draft(id="draft-session", session_id="thread-1")

    result = await service.resolve_draft(company_id="company-1", user_id="emp-1", thread_id="thread-1")
    assert result.status == "resolved"
    assert result.candidates[0].id == "draft-session"


@pytest.mark.asyncio
async def test_falls_back_to_users_own_drafts_when_thread_has_none(service, draft_repo):
    draft_repo.get_latest_for_session.return_value = None
    draft_repo.list_drafts.return_value = [_draft(id="draft-own")]

    result = await service.resolve_draft(company_id="company-1", user_id="emp-1", thread_id="thread-empty")
    assert result.status == "resolved"
    assert result.candidates[0].id == "draft-own"


@pytest.mark.asyncio
async def test_more_than_one_own_draft_is_ambiguous_never_guessed(service, draft_repo):
    draft_repo.get_latest_for_session.return_value = None
    draft_repo.list_drafts.return_value = [_draft(id="draft-a"), _draft(id="draft-b")]

    result = await service.resolve_draft(company_id="company-1", user_id="emp-1", thread_id=None)
    assert result.status == "ambiguous"
    assert len(result.candidates) == 2


@pytest.mark.asyncio
async def test_nothing_found_anywhere_is_unresolved(service, draft_repo):
    draft_repo.get_latest_for_session.return_value = None
    draft_repo.list_drafts.return_value = []

    result = await service.resolve_draft(company_id="company-1", user_id="emp-1", thread_id="thread-1")
    assert result.status == "unresolved"
    assert result.candidates == ()


@pytest.mark.asyncio
async def test_resolve_document_prefers_explicit_then_focus_then_falls_back(service, document_repo):
    document_repo.get_by_id.side_effect = [None, _document(id="uploads/focus.pdf")]

    result = await service.resolve_document(
        company_id="company-1",
        user_id="emp-1",
        explicit_document_id="uploads/missing.pdf",
        focus_document_id="uploads/focus.pdf",
    )
    assert result.status == "resolved"
    assert result.candidates[0].id == "uploads/focus.pdf"
    assert document_repo.get_by_id.await_count == 2


@pytest.mark.asyncio
async def test_resolve_document_falls_back_to_owners_recent_documents(service, document_repo):
    document_repo.get_by_id.return_value = None
    document_repo.list_for_owner.return_value = [_document(id="uploads/recent.pdf")]

    result = await service.resolve_document(company_id="company-1", user_id="emp-1")
    assert result.status == "resolved"
    assert result.candidates[0].id == "uploads/recent.pdf"
