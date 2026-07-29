import os
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.config import settings
from app.ai.llms import get_llm_client
from app.infrastructure.cache.redis import RedisCache
from app.infrastructure.storage.local import LocalStorage
from app.infrastructure.storage.s3 import S3Storage
from app.infrastructure.vectorstore.qdrant import QdrantStore
from app.ai.embeddings.service import EmbeddedChunk


# ==========================================
# vLLM Client Tests
# ==========================================
@pytest.mark.asyncio
@patch("app.infrastructure.providers.vllm.ChatOpenAI")
async def test_vllm_client_generate(mock_chat_openai):
    mock_instance = MagicMock()
    mock_instance.ainvoke = AsyncMock()
    mock_instance.ainvoke.return_value.content = "vLLM test response"
    mock_chat_openai.return_value = mock_instance

    client = get_llm_client(provider="vllm", base_url="http://localhost:8000/v1", model="qwen")
    response = await client.generate([{"role": "user", "content": "hello"}])

    assert response == "vLLM test response"
    mock_instance.ainvoke.assert_called_once()


# ==========================================
# Redis Cache Tests
# ==========================================
@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_cache_operations(mock_aioredis):
    mock_client = AsyncMock()
    mock_client.get.return_value = "cached_val"
    mock_client.exists.return_value = 1
    mock_aioredis.from_url.return_value = mock_client

    cache = RedisCache(redis_url="redis://localhost:6379/0")
    
    val = await cache.get("test_key")
    exists = await cache.exists("test_key")
    
    assert val == "cached_val"
    assert exists is True
    mock_client.get.assert_called_once_with("test_key")
    mock_client.exists.assert_called_once_with("test_key")


# ==========================================
# Local Storage Tests
# ==========================================
@pytest.mark.asyncio
async def test_local_storage(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    file_path = "subfolder/test_file.txt"
    content = b"hello local storage"

    # Save
    saved_path = await storage.put_file(file_path, content)
    assert saved_path == file_path
    assert os.path.exists(os.path.join(str(tmp_path), file_path))

    # Read
    read_content = await storage.get_file(file_path)
    assert read_content == content

    # Delete
    deleted = await storage.delete_file(file_path)
    assert deleted is True
    assert not os.path.exists(os.path.join(str(tmp_path), file_path))


@pytest.mark.asyncio
async def test_local_storage_traversal_protection(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    # Directory traversal path
    bad_path = "../traversal_file.txt"

    with pytest.raises(ValueError):
        await storage.put_file(bad_path, b"dangerous data")


# ==========================================
# S3 Storage Tests
# ==========================================
@pytest.mark.asyncio
@patch("app.infrastructure.storage.s3.boto3")
async def test_s3_storage_operations(mock_boto3):
    mock_s3_client = MagicMock()
    mock_boto3.client.return_value = mock_s3_client
    
    # Mock download response
    mock_body = MagicMock()
    mock_body.read.return_value = b"s3 content"
    mock_s3_client.get_object.return_value = {"Body": mock_body}

    storage = S3Storage(
        bucket_name="test-bucket",
        endpoint_url="http://minio:9000",
        access_key="admin",
        secret_key="admin"
    )

    # Put
    uri = await storage.put_file("folder/file.bin", b"bytes")
    assert uri == "s3://test-bucket/folder/file.bin"
    mock_s3_client.put_object.assert_called_once_with(
        Bucket="test-bucket", Key="folder/file.bin", Body=b"bytes"
    )

    # Get
    data = await storage.get_file("folder/file.bin")
    assert data == b"s3 content"


# ==========================================
# Qdrant Store Tests
# ==========================================
@pytest.mark.asyncio
@patch("app.infrastructure.vectorstore.qdrant.AsyncQdrantClient")
async def test_qdrant_store(mock_qdrant_client_class):
    mock_client = AsyncMock()
    mock_client.collection_exists.return_value = False
    mock_qdrant_client_class.return_value = mock_client

    store = QdrantStore(qdrant_url="http://qdrant:6333")
    
    # Create collection
    created = await store.create_collection("test_collection", vector_size=384)
    assert created is True
    mock_client.create_collection.assert_called_once()

    # Upsert
    chunks = [
        EmbeddedChunk(text="Chunk 1", vector=[0.1, 0.2], metadata={"src": "doc"}),
    ]
    upserted = await store.upsert_documents("test_collection", chunks)
    assert upserted is True
    mock_client.upsert.assert_called_once()

    # Similarity Search
    mock_hit = MagicMock()
    mock_hit.score = 0.95
    mock_hit.payload = {"text": "Found text", "src": "doc"}
    mock_client.search.return_value = [mock_hit]

    hits = await store.similarity_search("test_collection", [0.1, 0.2], limit=1)
    assert len(hits) == 1
    assert hits[0]["text"] == "Found text"
    assert hits[0]["score"] == 0.95
    assert hits[0]["metadata"]["src"] == "doc"


# ==========================================
# Database Connection Verification Tests
# ==========================================
from app.infrastructure.database.session import verify_db_connection

@pytest.mark.asyncio
@patch("app.infrastructure.database.session.AsyncSessionLocal")
async def test_verify_db_connection_success(mock_session_maker):
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 1
    mock_session.execute.return_value = mock_result
    
    # Mock async context manager
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_session
    mock_session_maker.return_value = mock_context_manager
    
    success = await verify_db_connection()
    assert success is True

