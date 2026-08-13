import logging
from typing import Any, Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisCache:
    """SOTA Asynchronous Redis Cache client wrapper."""

    def __init__(self, redis_url: str):
        """Initialize Redis Cache wrapper.

        Args:
            redis_url: Connection string (e.g. "redis://localhost:6379/0").
        """
        self.redis_url = redis_url
        self.client: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        """Establish async connection to Redis if not already connected."""
        if self.client is None:
            self.client = aioredis.from_url(
                self.redis_url, decode_responses=True
            )
            logger.info(f"Connected to Redis at {self.redis_url}")

    async def close(self) -> None:
        """Close the Redis connection pool."""
        if self.client is not None:
            # .close() is a deprecated alias for .aclose() on this redis-py
            # version and emits a DeprecationWarning on every call.
            await self.client.aclose()
            self.client = None
            logger.info("Closed Redis cache connection.")

    async def get(self, key: str) -> Optional[str]:
        """Get a value from the cache by key."""
        await self.connect()
        try:
            return await self.client.get(key)
        except Exception as e:
            logger.error(f"Redis get failed for key={key}: {e}")
            return None

    async def set(
        self, key: str, value: str, expire_seconds: Optional[int] = None
    ) -> bool:
        """Set a value in the cache with optional TTL."""
        await self.connect()
        try:
            await self.client.set(key, value, ex=expire_seconds)
            return True
        except Exception as e:
            logger.error(f"Redis set failed for key={key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete a key from the cache."""
        await self.connect()
        try:
            result = await self.client.delete(key)
            return result > 0
        except Exception as e:
            logger.error(f"Redis delete failed for key={key}: {e}")
            return False

    async def incr(self, key: str) -> Optional[int]:
        """Atomically increment a key (creating it at 1 if absent) and return the new value.

        Used for epoch-bump cache invalidation (see
        ``app.core.authz.cache.AuthzDecisionCache``): incrementing a
        namespace's epoch counter is O(1) and touches nothing else, unlike
        scanning and deleting every cached decision key under that
        namespace.
        """
        await self.connect()
        try:
            return await self.client.incr(key)
        except Exception as e:
            logger.error(f"Redis incr failed for key={key}: {e}")
            return None

    async def exists(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        await self.connect()
        try:
            result = await self.client.exists(key)
            return result > 0
        except Exception as e:
            logger.error(f"Redis exists check failed for key={key}: {e}")
            return False

    async def clear(self) -> bool:
        """Flush the database keys."""
        await self.connect()
        try:
            await self.client.flushdb()
            logger.warning("Redis cache database cleared/flushed.")
            return True
        except Exception as e:
            logger.error(f"Redis clear failed: {e}")
            return False
