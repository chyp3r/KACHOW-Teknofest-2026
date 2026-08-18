"""Unit tests for `app.domains.drafts.service.DraftService` (the read-side
drafts API service -- not to be confused with `app.domains.documents.
draft_service.DraftService`, which generates drafts)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.exceptions.not_found import NotFoundException
from app.api.exceptions.validation import ValidationException
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


@pytest.mark.asyncio
async def test_update_destination_resolves_a_matching_unit_id(service, repository):
    draft = _draft()
    repository.get_by_id.return_value = draft
    repository.update_destination.return_value = draft
    matched_unit = MagicMock(id="unit-42")

    with patch("app.domains.drafts.service.UnitRepository") as unit_repository_cls:
        unit_repository_cls.return_value.get_by_name = AsyncMock(return_value=matched_unit)
        await service.update_destination("draft-1", "İnsan Kaynakları", "company-1")

    unit_repository_cls.return_value.get_by_name.assert_awaited_once_with(
        "İnsan Kaynakları", "company-1"
    )
    repository.update_destination.assert_awaited_once_with(
        draft,
        destination="İnsan Kaynakları",
        destination_unit_id="unit-42",
        destination_justification="Kullanıcı tarafından manuel olarak seçildi.",
    )


@pytest.mark.asyncio
async def test_update_destination_accepts_a_custom_name_with_no_matching_unit(service, repository):
    """A destination need not match a real `units` row -- see
    `DraftModel.destination_unit_id`'s own docstring."""
    draft = _draft()
    repository.get_by_id.return_value = draft
    repository.update_destination.return_value = draft

    with patch("app.domains.drafts.service.UnitRepository") as unit_repository_cls:
        unit_repository_cls.return_value.get_by_name = AsyncMock(return_value=None)
        await service.update_destination("draft-1", "Özel Birim", "company-1")

    repository.update_destination.assert_awaited_once_with(
        draft,
        destination="Özel Birim",
        destination_unit_id=None,
        destination_justification="Kullanıcı tarafından manuel olarak seçildi.",
    )


@pytest.mark.asyncio
async def test_update_destination_rejects_a_blank_value(service, repository):
    with pytest.raises(ValidationException):
        await service.update_destination("draft-1", "   ", "company-1")

    repository.get_by_id.assert_not_called()
    repository.update_destination.assert_not_called()


@pytest.mark.asyncio
async def test_update_destination_raises_not_found_for_a_missing_draft(service, repository):
    repository.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await service.update_destination("does-not-exist", "İnsan Kaynakları", "company-1")

    repository.update_destination.assert_not_called()
