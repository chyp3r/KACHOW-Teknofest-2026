from app.core.config import settings
from app.infrastructure.cache.redis import RedisCache

# Lazy singleton instance
_cache = None


def get_cache() -> RedisCache:
    """Get the active global Redis cache client instance."""
    global _cache
    if _cache is None:
        _cache = RedisCache(redis_url=settings.REDIS_URL)
    return _cache


__all__ = ["RedisCache", "get_cache"]
