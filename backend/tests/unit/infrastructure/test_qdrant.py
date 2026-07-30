import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.infrastructure.vectorstore.qdrant import QdrantStore
from app.ai.embeddings.service import EmbeddedChunk

@pytest.fixture
def store():
    with patch("app.infrastructure.vectorstore.qdrant.AsyncQdrantClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        store_instance = QdrantStore("http://test-qdrant:6333")
        yield store_instance

@pytest.mark.asyncio
async def test_create_collection_exists(store):
    store.client.collection_exists.return_value = True
    assert await store.create_collection("col1", 384) is True
    store.client.create_collection.assert_not_called()

@pytest.mark.asyncio
async def test_create_collection_new(store):
    store.client.collection_exists.return_value = False
    
    assert await store.create_collection("col1", 384, "euclidean") is True
    store.client.create_collection.assert_called_once()
    args, kwargs = store.client.create_collection.call_args
    assert kwargs["collection_name"] == "col1"
    
    assert await store.create_collection("col2", 384, "dot") is True
    
@pytest.mark.asyncio
async def test_create_collection_exception(store):
    store.client.collection_exists.side_effect = Exception("error")
    assert await store.create_collection("col1", 384) is False

@pytest.mark.asyncio
async def test_upsert_documents_empty(store):
    assert await store.upsert_documents("col1", []) is True

@pytest.mark.asyncio
async def test_upsert_documents_success(store):
    chunks = [EmbeddedChunk(text="t", vector=[0.1], metadata={"a": 1})]
    assert await store.upsert_documents("col1", chunks) is True
    store.client.upsert.assert_called_once()

@pytest.mark.asyncio
async def test_upsert_documents_exception(store):
    chunks = [EmbeddedChunk(text="t", vector=[0.1], metadata={"a": 1})]
    store.client.upsert.side_effect = Exception("error")
    assert await store.upsert_documents("col1", chunks) is False

@pytest.mark.asyncio
async def test_similarity_search_success(store):
    mock_hit = MagicMock()
    mock_hit.score = 0.95
    mock_hit.payload = {"text": "Found text", "src": "doc"}
    mock_response = MagicMock()
    mock_response.points = [mock_hit]
    store.client.query_points.return_value = mock_response
    
    results = await store.similarity_search("col1", [0.1], limit=1)
    assert len(results) == 1
    assert results[0]["text"] == "Found text"
    
@pytest.mark.asyncio
async def test_similarity_search_exception(store):
    store.client.query_points.side_effect = Exception("error")
    results = await store.similarity_search("col1", [0.1], limit=1)
    assert results == []

@pytest.mark.asyncio
async def test_delete_collection_success(store):
    store.client.collection_exists.return_value = True
    assert await store.delete_collection("col1") is True
    store.client.delete_collection.assert_called_once_with("col1")

@pytest.mark.asyncio
async def test_delete_collection_exception(store):
    store.client.collection_exists.side_effect = Exception("error")
    assert await store.delete_collection("col1") is False
