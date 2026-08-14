from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.model.document_model import DocumentModel
from app.domains.pools.model.document_pool_item_model import DocumentPoolItemModel
from app.domains.pools.model.document_pool_model import DocumentPoolModel
from app.domains.pools.repository import DocumentPoolItemRepository, DocumentPoolRepository


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


def _pool(**overrides) -> DocumentPoolModel:
    fields = dict(
        id="pool-1", company_id="company-1", owner_type="user", owner_id="user-1",
        name="Kişisel Havuz", is_default=True,
    )
    fields.update(overrides)
    return DocumentPoolModel(**fields)


def _item(**overrides) -> DocumentPoolItemModel:
    fields = dict(
        id="item-1", company_id="company-1", pool_id="pool-1", document_id="doc-1",
        added_by="admin-1", source="manager_push", note=None, acknowledged_at=None,
    )
    fields.update(overrides)
    return DocumentPoolItemModel(**fields)


class TestDocumentPoolRepository:
    @pytest.fixture
    def repo(self, mock_session):
        return DocumentPoolRepository(mock_session)

    async def test_get_or_create_default_returns_existing_pool(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = _pool()
        mock_session.execute.return_value = mock_result

        pool = await repo.get_or_create_default("user", "user-1", "company-1", name="Kişisel Havuz")

        assert pool.id == "pool-1"
        mock_session.add.assert_not_called()

    async def test_get_or_create_default_creates_when_missing(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        pool = await repo.get_or_create_default("user", "user-1", "company-1", name="Kişisel Havuz")

        assert pool.owner_type == "user"
        assert pool.owner_id == "user-1"
        assert pool.is_default is True
        mock_session.add.assert_called_once()
        mock_session.flush.assert_awaited_once()


class TestDocumentPoolItemRepository:
    @pytest.fixture
    def repo(self, mock_session):
        return DocumentPoolItemRepository(mock_session)

    async def test_exists_true(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "item-1"
        mock_session.execute.return_value = mock_result

        assert await repo.exists("pool-1", "doc-1") is True

    async def test_exists_false(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        assert await repo.exists("pool-1", "doc-1") is False

    async def test_list_for_pool_joins_document(self, repo, mock_session):
        item = _item()
        document = DocumentModel(
            id="doc-1", company_id="company-1", owner_id="user-1", file_name="a.pdf"
        )
        mock_result = MagicMock()
        mock_result.all.return_value = [(item, document)]
        mock_session.execute.return_value = mock_result

        result = await repo.list_for_pool("pool-1", "company-1")

        assert result == [(item, document)]

    async def test_acknowledge_sets_timestamp(self, repo, mock_session):
        item = _item(acknowledged_at=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = item
        mock_session.execute.return_value = mock_result

        acknowledged = await repo.acknowledge("item-1", "company-1")

        assert acknowledged.acknowledged_at is not None
        mock_session.flush.assert_awaited_once()

    async def test_acknowledge_returns_none_when_not_found(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        assert await repo.acknowledge("missing", "company-1") is None

    async def test_delete_true_when_removed(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session.execute.return_value = mock_result

        assert await repo.delete("item-1", "company-1") is True
