"""Unit tests for the rate-limit dependency.

The case that matters is the unreachable store. Rate limiting is a protection
mechanism, not a correctness requirement, so a cache outage must not take the
protected endpoints down with it -- and before this it did: every route behind
`rate_limit()` returned 500 while Redis was restarting, including `/auth/login`.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.exceptions.rate_limit import RateLimitException
from app.api.rate_limit import rate_limit


def _request(ip: str = "203.0.113.7") -> MagicMock:
    request = MagicMock()
    request.headers = {}
    request.client = MagicMock()
    request.client.host = ip
    return request


def _cache(counts: list) -> MagicMock:
    """Build a cache whose pipeline returns `counts` from execute()."""
    pipeline = MagicMock()
    pipeline.execute = AsyncMock(return_value=counts)
    cache = MagicMock()
    cache.connect = AsyncMock()
    cache.client.pipeline = MagicMock(return_value=pipeline)
    return cache


@pytest.mark.asyncio
async def test_request_within_the_window_is_allowed():
    dependency = rate_limit(max_requests=5, window_seconds=60, key_prefix="t")
    with patch("app.api.rate_limit.get_cache", return_value=_cache([0, 1, 3, True])):
        assert await dependency(_request()) is None


@pytest.mark.asyncio
async def test_request_over_the_limit_is_rejected():
    dependency = rate_limit(max_requests=5, window_seconds=60, key_prefix="t")
    with patch("app.api.rate_limit.get_cache", return_value=_cache([0, 1, 6, True])):
        with pytest.raises(RateLimitException):
            await dependency(_request())


@pytest.mark.asyncio
async def test_exactly_at_the_limit_is_still_allowed():
    """The limit is a maximum, not an exclusive bound."""
    dependency = rate_limit(max_requests=5, window_seconds=60, key_prefix="t")
    with patch("app.api.rate_limit.get_cache", return_value=_cache([0, 1, 5, True])):
        assert await dependency(_request()) is None


# ==========================================
# Degradation
# ==========================================
@pytest.mark.asyncio
async def test_an_unreachable_store_fails_open():
    """A Redis outage previously returned 500 from login, chat and upload -- an
    unavailable cache locked every user out of the system."""
    cache = MagicMock()
    cache.connect = AsyncMock(side_effect=ConnectionError("connection refused"))
    dependency = rate_limit(max_requests=5, window_seconds=60, key_prefix="t")

    with patch("app.api.rate_limit.get_cache", return_value=cache):
        assert await dependency(_request()) is None


@pytest.mark.asyncio
async def test_a_failing_pipeline_also_fails_open():
    """The store can accept the connection and still fail mid-pipeline."""
    cache = _cache([])
    cache.client.pipeline.return_value.execute = AsyncMock(
        side_effect=ConnectionError("reset by peer")
    )
    dependency = rate_limit(max_requests=5, window_seconds=60, key_prefix="t")

    with patch("app.api.rate_limit.get_cache", return_value=cache):
        assert await dependency(_request()) is None


@pytest.mark.asyncio
async def test_failing_open_does_not_swallow_the_limit_exception():
    """The over-limit rejection must not be caught by the degradation handler --
    RateLimitException is raised after the store call, deliberately outside it."""
    dependency = rate_limit(max_requests=1, window_seconds=60, key_prefix="t")
    with patch("app.api.rate_limit.get_cache", return_value=_cache([0, 1, 99, True])):
        with pytest.raises(RateLimitException):
            await dependency(_request())


@pytest.mark.asyncio
async def test_client_is_identified_by_the_forwarded_header_when_present():
    """Behind a proxy every request carries the proxy's IP, so the limit would be
    shared across all clients rather than applied per client."""
    dependency = rate_limit(max_requests=5, window_seconds=60, key_prefix="t")
    request = _request(ip="10.0.0.1")
    request.headers = {"X-Forwarded-For": "198.51.100.4, 10.0.0.1"}
    cache = _cache([0, 1, 1, True])

    with patch("app.api.rate_limit.get_cache", return_value=cache):
        await dependency(request)

    key = cache.client.pipeline.return_value.zadd.call_args.args[0]
    assert key == "t:198.51.100.4"
