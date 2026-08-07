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

import logging
import time
from typing import Callable
from uuid import uuid4
from fastapi import Depends, Request

from app.core.config import settings
from app.infrastructure.cache import get_cache
from app.api.exceptions.rate_limit import RateLimitException

logger = logging.getLogger(__name__)


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
        # X-Forwarded-For is only meaningful -- and only safe -- behind a proxy
        # that overwrites rather than appends to it. Trusting it unconditionally
        # let a client set a fresh header per request and never accumulate a
        # count at all; see TRUST_PROXY_HEADERS' docstring in core/config.py.
        if settings.TRUST_PROXY_HEADERS and "X-Forwarded-For" in request.headers:
            client_ip = request.headers["X-Forwarded-For"].split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        cache = get_cache()
        redis_key = f"{key_prefix}:{client_ip}"
        now = int(time.time())
        window_start = now - window_seconds
        # The ZSET member must be unique per request, not per second. Redis
        # ZADD on an existing member updates its score rather than adding a
        # second entry, so using the bare timestamp as the member collapsed
        # every request within the same second into one: N requests sent
        # inside one second scored ZCARD=1, and the "5 requests per 60
        # seconds" limit could never see more than `window_seconds` distinct
        # entries no matter how many requests actually arrived. Appending a
        # random suffix keeps the score (used for the window trim below)
        # while making every member distinct.
        member = f"{now}:{uuid4().hex}"

        # Fail open, not closed. Rate limiting is a protection mechanism, not a
        # correctness requirement: if the counter is unreachable we cannot know
        # whether this request is over the limit, and the safe answer is to serve
        # it. Failing closed meant a Redis restart returned 500 from /auth/login,
        # /auth/refresh, /chat/stream, /chat/resume and /documents/analyze -- an
        # unavailable cache locked every user out of the system.
        #
        # The tradeoff is real and worst for auth:login, whose 5/60s limit is a
        # brute-force defence. It is still the right side to fail on. An attacker
        # cannot cause this branch (they would have to take Redis down first, and
        # if they can do that the limiter is not the exposure), whereas an
        # operator restarting Redis triggers it every time.
        try:
            await cache.connect()
            pipe = cache.client.pipeline()
            # Remove counts outside the current window
            pipe.zremrangebyscore(redis_key, "-inf", window_start)
            # Record this request under its own unique member (see above)
            pipe.zadd(redis_key, {member: now})
            # Count requests in window
            pipe.zcard(redis_key)
            # Reset TTL so key expires after inactivity
            pipe.expire(redis_key, window_seconds)
            results = await pipe.execute()
        except Exception:
            logger.warning(
                "Rate limit store unavailable; allowing '%s' through unmetered.",
                key_prefix,
                exc_info=True,
            )
            return

        request_count = results[2]
        if request_count > max_requests:
            raise RateLimitException(
                message=f"Too many requests. Maximum {max_requests} requests per {window_seconds} seconds allowed."
            )

    return _check_rate_limit
