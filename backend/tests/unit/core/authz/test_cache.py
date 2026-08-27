"""Unit tests for `AuthzDecisionCache` (app.core.authz.cache).

`RedisCache` is mocked directly rather than exercised through
`aioredis` -- this file tests the wrapper's own logic (epoch-scoped key
construction, `Decision` (de)serialization, the `cacheable` gate), not
Redis itself (see tests/unit/infrastructure/test_redis.py for that).
"""

from unittest.mock import AsyncMock

import pytest

from app.core.authz.cache import AuthzDecisionCache
from app.core.authz.engine import Decision
from app.infrastructure.cache.redis import RedisCache


@pytest.fixture
def redis():
    return AsyncMock(spec=RedisCache)


@pytest.fixture
def cache(redis):
    return AuthzDecisionCache(redis)


# ==========================================
# current_epoch
# ==========================================
@pytest.mark.asyncio
async def test_current_epoch_defaults_to_zero_when_unset(redis, cache):
    redis.get.return_value = None

    assert await cache.current_epoch("company-1") == 0
    redis.get.assert_awaited_once_with("authz:epoch:company-1")


@pytest.mark.asyncio
async def test_current_epoch_parses_a_valid_integer(redis, cache):
    redis.get.return_value = "7"

    assert await cache.current_epoch("company-1") == 7


@pytest.mark.asyncio
async def test_current_epoch_falls_back_to_zero_on_a_corrupt_value(redis, cache):
    """A Redis value that isn't a plain int must not crash authorization --
    it degrades to epoch 0, same as unset."""
    redis.get.return_value = "not-a-number"

    assert await cache.current_epoch("company-1") == 0


# ==========================================
# bump_epoch
# ==========================================
@pytest.mark.asyncio
async def test_bump_epoch_increments_the_epoch_key(redis, cache):
    redis.incr.return_value = 3

    await cache.bump_epoch("company-1")

    redis.incr.assert_awaited_once_with("authz:epoch:company-1")


@pytest.mark.asyncio
async def test_bump_epoch_warns_but_does_not_raise_when_redis_is_unavailable(redis, cache, caplog):
    redis.incr.return_value = None

    with caplog.at_level("WARNING"):
        await cache.bump_epoch("company-1")

    assert "company-1" in caplog.text


# ==========================================
# get
# ==========================================
@pytest.mark.asyncio
async def test_get_returns_none_on_a_cache_miss(redis, cache):
    redis.get.return_value = None

    result = await cache.get("company-1", "user-1", "read", "document", "doc-1")

    assert result is None


@pytest.mark.asyncio
async def test_get_reconstructs_the_decision_on_a_cache_hit(redis, cache):
    # First call resolves the epoch (0, unset), second is the decision lookup.
    redis.get.side_effect = [
        None,
        '{"permit": true, "reason": "owner", "matched_rule": "employee:read", "cacheable": true}',
    ]

    result = await cache.get("company-1", "user-1", "read", "document", "doc-1")

    assert result == Decision(permit=True, reason="owner", matched_rule="employee:read", cacheable=True)
    assert redis.get.await_args_list[1].args[0] == "authz:d:company-1:0:user-1:read:document:doc-1"


@pytest.mark.asyncio
async def test_get_uses_a_dash_placeholder_for_a_missing_resource_id(redis, cache):
    redis.get.side_effect = [None, None]

    await cache.get("company-1", "user-1", "list", "document", None)

    assert redis.get.await_args_list[1].args[0] == "authz:d:company-1:0:user-1:list:document:-"


@pytest.mark.asyncio
async def test_get_treats_corrupt_cached_json_as_a_miss(redis, cache):
    redis.get.side_effect = [None, "{not valid json"]

    result = await cache.get("company-1", "user-1", "read", "document", "doc-1")

    assert result is None


# ==========================================
# set
# ==========================================
@pytest.mark.asyncio
async def test_set_never_persists_an_uncacheable_decision(redis, cache):
    decision = Decision(permit=False, reason="tenant boundary", cacheable=False)

    await cache.set("company-1", "user-1", "read", "document", "doc-1", decision)

    redis.set.assert_not_awaited()
    redis.get.assert_not_awaited()  # never even resolves the epoch


@pytest.mark.asyncio
async def test_set_persists_a_cacheable_decision_under_the_epoch_scoped_key(redis, cache):
    redis.get.return_value = "2"  # current epoch
    decision = Decision(permit=True, reason="owner", matched_rule="employee:read")

    await cache.set("company-1", "user-1", "read", "document", "doc-1", decision)

    redis.set.assert_awaited_once()
    key, payload = redis.set.await_args.args
    assert key == "authz:d:company-1:2:user-1:read:document:doc-1"
    assert '"permit": true' in payload
    assert redis.set.await_args.kwargs["expire_seconds"] == 60
