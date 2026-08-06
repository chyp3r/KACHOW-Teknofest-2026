"""Unit tests for the rate-limit dependency.

Two cases matter more than the happy path.

The unreachable store: rate limiting is a protection mechanism, not a
correctness requirement, so a cache outage must not take the protected
endpoints down with it -- and before this it did: every route behind
`rate_limit()` returned 500 while Redis was restarting, including `/auth/login`.

Real counting semantics: the original implementation was verified only against
a mock whose `pipeline.execute()` returned hand-written counts, which is exactly
why it shipped broken. `pipe.zadd(redis_key, {str(now): now})` used the
whole-second timestamp as the ZSET *member*; Redis ZADD on an existing member
updates its score rather than inserting a new entry, so `zcard` returned the
number of distinct *seconds* seen in the window, not the number of requests.
Ten thousand login attempts sent inside one second scored ZCARD=1 against a
"5 requests per 60 seconds" limit, and every one of them was served. The mock
could not catch this because it never modeled Redis's collapse-on-duplicate-
member behaviour -- `FakeRedisZsetPipeline` below does, backed by a real
in-memory sorted set, so these tests exercise the actual bug class rather than
whatever the mock was told to return.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.exceptions.rate_limit import RateLimitException
from app.api.rate_limit import rate_limit


def _request(ip: str = "203.0.113.7", headers: dict | None = None) -> MagicMock:
    request = MagicMock()
    request.headers = headers or {}
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


class FakeRedisZsetPipeline:
    """A real in-memory ZSET behind the same four-call shape rate_limit() uses.

    Chainable like redis-py's own pipeline (each call queues an op and returns
    self), but backed by an actual `{member: score}` dict per key -- so ZADD on
    a member that already exists updates its score instead of adding a second
    entry, which is the exact Redis behaviour the bug depended on and a
    hand-written mock cannot reproduce.
    """

    def __init__(self, store: dict[str, dict[str, float]]):
        self._store = store
        self._queue: list[tuple[str, tuple]] = []

    def zremrangebyscore(self, key, min_score, max_score):
        self._queue.append(("zremrangebyscore", (key, min_score, max_score)))
        return self

    def zadd(self, key, mapping):
        self._queue.append(("zadd", (key, dict(mapping))))
        return self

    def zcard(self, key):
        self._queue.append(("zcard", (key,)))
        return self

    def expire(self, key, seconds):
        self._queue.append(("expire", (key, seconds)))
        return self

    async def execute(self):
        results = []
        for op, args in self._queue:
            zset = self._store.setdefault(args[0], {})
            if op == "zremrangebyscore":
                _, lo, hi = args
                lo = float("-inf") if lo == "-inf" else float(lo)
                hi = float("inf") if hi == "+inf" else float(hi)
                removed = [m for m, s in zset.items() if lo <= s <= hi]
                for m in removed:
                    del zset[m]
                results.append(len(removed))
            elif op == "zadd":
                _, mapping = args
                added = sum(1 for m in mapping if m not in zset)
                zset.update(mapping)  # <-- the real-Redis collapse-on-duplicate behaviour
                results.append(added)
            elif op == "zcard":
                results.append(len(zset))
            elif op == "expire":
                results.append(True)
        self._queue.clear()
        return results


def _fake_redis_cache() -> MagicMock:
    """A cache whose pipeline() is a fresh FakeRedisZsetPipeline over shared state."""
    store: dict[str, dict[str, float]] = {}
    cache = MagicMock()
    cache.connect = AsyncMock()
    cache.client.pipeline = MagicMock(side_effect=lambda: FakeRedisZsetPipeline(store))
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
# Real counting semantics (the regression this file exists for)
# ==========================================
@pytest.mark.asyncio
async def test_requests_within_the_same_second_are_all_counted():
    """The bug, reproduced directly: with a shared member per second, N requests
    sent inside one second used to score ZCARD=1 and the limit never fired."""
    dependency = rate_limit(max_requests=3, window_seconds=60, key_prefix="t")
    cache = _fake_redis_cache()

    with patch("app.api.rate_limit.get_cache", return_value=cache):
        with patch("app.api.rate_limit.time.time", return_value=1_000_000.0):
            for _ in range(3):
                await dependency(_request())  # 3 requests, same second, all allowed
            with pytest.raises(RateLimitException):
                await dependency(_request())  # the 4th, same second, must be rejected


@pytest.mark.asyncio
async def test_each_request_gets_its_own_zset_member():
    """Directly asserts the fix: N calls in the same second must produce N
    distinct members, not one member updated N times."""
    dependency = rate_limit(max_requests=100, window_seconds=60, key_prefix="t")
    cache = _fake_redis_cache()

    with patch("app.api.rate_limit.get_cache", return_value=cache):
        with patch("app.api.rate_limit.time.time", return_value=1_000_000.0):
            for _ in range(5):
                await dependency(_request())

    call_count = cache.client.pipeline.call_args_list  # pipeline() called once per request
    assert len(call_count) == 5
    # Inspect the shared backing store through a fresh pipeline over the same dict.
    store = cache.client.pipeline()._store
    stored = next(iter(store.values()))
    assert len(stored) == 5, "5 requests must leave 5 distinct ZSET members"


@pytest.mark.asyncio
async def test_requests_outside_the_window_are_not_counted():
    dependency = rate_limit(max_requests=3, window_seconds=60, key_prefix="t")
    cache = _fake_redis_cache()

    with patch("app.api.rate_limit.get_cache", return_value=cache):
        with patch("app.api.rate_limit.time.time", return_value=1_000_000.0):
            for _ in range(3):
                await dependency(_request())
        # 61 seconds later: the old entries fall outside the window and are
        # trimmed by zremrangebyscore before this request is counted.
        with patch("app.api.rate_limit.time.time", return_value=1_000_061.0):
            await dependency(_request())  # must not raise


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


# ==========================================
# Client identification
# ==========================================
@pytest.mark.asyncio
async def test_forwarded_header_is_ignored_by_default():
    """With no reverse proxy configured, X-Forwarded-For is attacker-controlled
    input: a client could set a fresh value per request and never accumulate a
    count in any single Redis key. The real TCP peer is used instead."""
    dependency = rate_limit(max_requests=5, window_seconds=60, key_prefix="t")
    request = _request(ip="10.0.0.1", headers={"X-Forwarded-For": "198.51.100.4"})
    cache = _cache([0, 1, 1, True])

    with patch("app.api.rate_limit.get_cache", return_value=cache):
        await dependency(request)

    key = cache.client.pipeline.return_value.zadd.call_args.args[0]
    assert key == "t:10.0.0.1"


@pytest.mark.asyncio
async def test_forwarded_header_is_honoured_when_proxy_is_trusted():
    dependency = rate_limit(max_requests=5, window_seconds=60, key_prefix="t")
    request = _request(ip="10.0.0.1", headers={"X-Forwarded-For": "198.51.100.4, 10.0.0.1"})
    cache = _cache([0, 1, 1, True])

    with patch("app.api.rate_limit.settings.TRUST_PROXY_HEADERS", True):
        with patch("app.api.rate_limit.get_cache", return_value=cache):
            await dependency(request)

    key = cache.client.pipeline.return_value.zadd.call_args.args[0]
    assert key == "t:198.51.100.4"


@pytest.mark.asyncio
async def test_spoofed_forwarded_header_no_longer_defeats_the_limit():
    """The scenario the old unconditional trust enabled: a fresh IP per request
    used to buy a fresh Redis key per request, so no key ever reached the limit.
    With the header ignored, every request lands in the same key regardless of
    what the client claims."""
    dependency = rate_limit(max_requests=3, window_seconds=60, key_prefix="t")
    cache = _fake_redis_cache()

    with patch("app.api.rate_limit.get_cache", return_value=cache):
        with patch("app.api.rate_limit.time.time", return_value=1_000_000.0):
            for i in range(3):
                request = _request(
                    ip="203.0.113.7",
                    headers={"X-Forwarded-For": f"10.0.0.{i}"},  # different every time
                )
                await dependency(request)
            with pytest.raises(RateLimitException):
                await dependency(_request(ip="203.0.113.7", headers={"X-Forwarded-For": "10.0.0.99"}))
