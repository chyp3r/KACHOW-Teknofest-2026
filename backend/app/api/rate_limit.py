"""Redis-backed sliding window rate limiter as a FastAPI dependency.

Usage example:
    from app.api.rate_limit import rate_limit

    @router.post("/login")
    async def login(
        schema: LoginRequest,
        _: None = Depends(rate_limit(max_requests=5, window_seconds=60, key_prefix="login")),
    ):
        ...
"""

import time
from typing import Callable
from fastapi import Depends, Request

from app.infrastructure.cache import get_cache
from app.api.exceptions.rate_limit import RateLimitException


def rate_limit(
    max_requests: int = 10,
    window_seconds: int = 60,
    key_prefix: str = "rate_limit",
) -> Callable:
    """Factory returning a FastAPI dependency that enforces a sliding window rate limit.

    Args:
        max_requests: Maximum allowed requests within the time window.
        window_seconds: Duration of the sliding window in seconds.
        key_prefix: Redis key prefix to namespace different limits.

    Returns:
        An async FastAPI dependency function.
    """

    async def _check_rate_limit(request: Request) -> None:
        # Identify client by IP (works behind proxies with X-Forwarded-For)
        client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
        client_ip = client_ip.split(",")[0].strip()

        cache = get_cache()
        redis_key = f"{key_prefix}:{client_ip}"
        now = int(time.time())
        window_start = now - window_seconds

        await cache.connect()
        pipe = cache.client.pipeline()
        # Remove counts outside the current window
        pipe.zremrangebyscore(redis_key, "-inf", window_start)
        # Add current request timestamp
        pipe.zadd(redis_key, {str(now): now})
        # Count requests in window
        pipe.zcard(redis_key)
        # Reset TTL so key expires after inactivity
        pipe.expire(redis_key, window_seconds)
        results = await pipe.execute()

        request_count = results[2]
        if request_count > max_requests:
            raise RateLimitException(
                message=f"Too many requests. Maximum {max_requests} requests per {window_seconds} seconds allowed."
            )

    return _check_rate_limit
