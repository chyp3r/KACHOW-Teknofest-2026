import pytest
from unittest.mock import AsyncMock, patch

from app.infrastructure.cache.redis import RedisCache

@pytest.fixture
def redis_cache():
    return RedisCache(redis_url="redis://localhost:6379/0")

@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_connect_and_close(mock_aioredis, redis_cache):
    mock_client = AsyncMock()
    mock_aioredis.from_url.return_value = mock_client
    
    await redis_cache.connect()
    assert redis_cache.client == mock_client
    mock_aioredis.from_url.assert_called_once_with("redis://localhost:6379/0", decode_responses=True)
    
    await redis_cache.close()
    mock_client.aclose.assert_called_once()
    assert redis_cache.client is None

@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_get(mock_aioredis, redis_cache):
    mock_client = AsyncMock()
    mock_client.get.return_value = "val"
    mock_aioredis.from_url.return_value = mock_client
    
    assert await redis_cache.get("key") == "val"
    mock_client.get.assert_called_once_with("key")

@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_get_exception(mock_aioredis, redis_cache):
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("DB error")
    mock_aioredis.from_url.return_value = mock_client
    
    assert await redis_cache.get("key") is None

@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_set(mock_aioredis, redis_cache):
    mock_client = AsyncMock()
    mock_aioredis.from_url.return_value = mock_client
    
    assert await redis_cache.set("key", "val", expire_seconds=10) is True
    mock_client.set.assert_called_once_with("key", "val", ex=10)

@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_set_exception(mock_aioredis, redis_cache):
    mock_client = AsyncMock()
    mock_client.set.side_effect = Exception("DB error")
    mock_aioredis.from_url.return_value = mock_client
    
    assert await redis_cache.set("key", "val") is False

@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_delete(mock_aioredis, redis_cache):
    mock_client = AsyncMock()
    mock_client.delete.return_value = 1
    mock_aioredis.from_url.return_value = mock_client
    
    assert await redis_cache.delete("key") is True
    mock_client.delete.assert_called_once_with("key")

@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_delete_exception(mock_aioredis, redis_cache):
    mock_client = AsyncMock()
    mock_client.delete.side_effect = Exception("DB error")
    mock_aioredis.from_url.return_value = mock_client
    
    assert await redis_cache.delete("key") is False

@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_exists(mock_aioredis, redis_cache):
    mock_client = AsyncMock()
    mock_client.exists.return_value = 1
    mock_aioredis.from_url.return_value = mock_client
    
    assert await redis_cache.exists("key") is True
    mock_client.exists.assert_called_once_with("key")

@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_exists_exception(mock_aioredis, redis_cache):
    mock_client = AsyncMock()
    mock_client.exists.side_effect = Exception("DB error")
    mock_aioredis.from_url.return_value = mock_client
    
    assert await redis_cache.exists("key") is False

@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_publish(mock_aioredis, redis_cache):
    mock_client = AsyncMock()
    mock_aioredis.from_url.return_value = mock_client

    await redis_cache.publish("channel", "message")
    mock_client.publish.assert_called_once_with("channel", "message")

@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_publish_exception_is_swallowed(mock_aioredis, redis_cache):
    mock_client = AsyncMock()
    mock_client.publish.side_effect = Exception("DB error")
    mock_aioredis.from_url.return_value = mock_client

    # Fail-open: must not raise.
    await redis_cache.publish("channel", "message")

@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_clear(mock_aioredis, redis_cache):
    mock_client = AsyncMock()
    mock_aioredis.from_url.return_value = mock_client
    
    assert await redis_cache.clear() is True
    mock_client.flushdb.assert_called_once()

@pytest.mark.asyncio
@patch("app.infrastructure.cache.redis.aioredis")
async def test_redis_clear_exception(mock_aioredis, redis_cache):
    mock_client = AsyncMock()
    mock_client.flushdb.side_effect = Exception("DB error")
    mock_aioredis.from_url.return_value = mock_client
    
    assert await redis_cache.clear() is False
