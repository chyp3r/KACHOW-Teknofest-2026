import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.repository import DocumentRepository
from app.domains.documents.model.document_model import DocumentModel


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def repo(mock_session):
    return DocumentRepository(mock_session)


def _doc(storage_path="uploads/a.pdf", owner_id="user-1"):
    return DocumentModel(
        id=storage_path,
        owner_id=owner_id,
        file_name="evrak.pdf",
        document_type="official_letter",
        document_type_label="Resmî Yazı",
        compliance_status="compliant",
        summary="Test özeti.",
    )


@pytest.mark.asyncio
async def test_create(repo, mock_session):
    document = _doc()

    result = await repo.create(document)

    assert result is document
    mock_session.add.assert_called_once_with(document)
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_get_by_id_found(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = _doc()
    mock_session.execute.return_value = mock_result

    document = await repo.get_by_id("uploads/a.pdf")

    assert document is not None
    assert document.id == "uploads/a.pdf"


@pytest.mark.asyncio
async def test_get_by_id_missing(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    assert await repo.get_by_id("uploads/missing.pdf") is None


@pytest.mark.asyncio
async def test_list_for_owner_scopes_to_the_given_owner(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [_doc(owner_id="user-1")]
    mock_session.execute.return_value = mock_result

    documents = await repo.list_for_owner("user-1")

    assert len(documents) == 1
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_is_owned_by_true_for_the_actual_owner(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = _doc(owner_id="user-1")
    mock_session.execute.return_value = mock_result

    assert await repo.is_owned_by("uploads/a.pdf", "user-1") is True


@pytest.mark.asyncio
async def test_is_owned_by_false_for_a_different_user(repo, mock_session):
    """The core IDOR check: user B must not be recognised as the owner of
    user A's document."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = _doc(owner_id="user-1")
    mock_session.execute.return_value = mock_result

    assert await repo.is_owned_by("uploads/a.pdf", "user-2") is False


@pytest.mark.asyncio
async def test_is_owned_by_false_for_an_unregistered_document(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    assert await repo.is_owned_by("uploads/ghost.pdf", "user-1") is False
