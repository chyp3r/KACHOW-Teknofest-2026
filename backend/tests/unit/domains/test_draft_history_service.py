"""Unit tests for `app.domains.drafts.service.DraftService` (the read-side
drafts API service -- not to be confused with `app.domains.documents.
draft_service.DraftService`, which generates drafts)."""

import pytest
from unittest.mock import AsyncMock

from app.api.exceptions.not_found import NotFoundException
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.service import DraftService


def _draft(draft_id="draft-1", session_id="session-1") -> DraftModel:
    return DraftModel(
        id=draft_id,
        user_id="user-1",
        session_id=session_id,
        document_id=None,
        version=1,
        content="İçerik",
        is_deleted=False,
    )


@pytest.fixture
def repository():
    return AsyncMock()


@pytest.fixture
def service(repository):
    return DraftService(repository)


@pytest.mark.asyncio
async def test_delete_draft_soft_deletes_the_whole_session_chain(service, repository):
    repository.get_by_id.return_value = _draft(session_id="session-1")

    await service.delete_draft("draft-1")

    repository.soft_delete_session.assert_awaited_once_with("session-1")
    repository.soft_delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_draft_falls_back_to_a_single_row_without_a_session(service, repository):
    """A direct `POST /documents/draft` call has no session_id -- there is no
    chain to collapse, so only that one row is marked."""
    repository.get_by_id.return_value = _draft(draft_id="draft-2", session_id=None)

    await service.delete_draft("draft-2")

    repository.soft_delete.assert_awaited_once_with("draft-2")
    repository.soft_delete_session.assert_not_called()


@pytest.mark.asyncio
async def test_delete_draft_raises_not_found_for_a_missing_or_already_deleted_draft(
    service, repository
):
    repository.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await service.delete_draft("does-not-exist")

    repository.soft_delete.assert_not_called()
    repository.soft_delete_session.assert_not_called()
