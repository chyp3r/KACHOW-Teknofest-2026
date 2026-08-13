"""Epoch-invalidated Redis cache for ``authorize()`` decisions.

Key design constraint from the tenancy plan: invalidation is an epoch bump
(``INCR authz:epoch:{company_id}``), never a ``SCAN``/``DEL`` sweep. A
multi-worker uvicorn deployment shares one Redis, and a decision's own key
already embeds the epoch it was computed under -- bumping the epoch makes
every previously-cached decision for that company unreachable (the next
lookup asks for a key under the new epoch, which is a cache miss) without
ever touching the old keys, which simply expire on their own TTL.

Fail-open on Redis errors: a cache miss (real or from an unreachable Redis)
just means ``AuthzService`` recomputes via ``engine.authorize`` -- slower,
never wrong. ``app.infrastructure.cache.redis.RedisCache`` already swallows
and logs its own exceptions for exactly this reason (see its module
docstring's neighbours, e.g. ``app.api.rate_limit`` being deliberately
fail-open); this module adds no additional try/except on top because there
is nothing left that could raise past that boundary.
"""

import json
import logging
from dataclasses import asdict
from typing import Optional

from app.core.authz.engine import Decision
from app.infrastructure.cache.redis import RedisCache

logger = logging.getLogger(__name__)

_DECISION_TTL_SECONDS = 60


def _epoch_key(company_id: str) -> str:
    return f"authz:epoch:{company_id}"


def _decision_key(
    company_id: str, epoch: int, user_id: str, action: str, resource_type: str, resource_id: Optional[str]
) -> str:
    return f"authz:d:{company_id}:{epoch}:{user_id}:{action}:{resource_type}:{resource_id or '-'}"


class AuthzDecisionCache:
    """Wraps ``RedisCache`` with the epoch-key scheme and ``Decision`` (de)serialization."""

    def __init__(self, cache: RedisCache):
        self._cache = cache

    async def current_epoch(self, company_id: str) -> int:
        """The active epoch for ``company_id``. Defaults to ``0`` if unset (a fresh company,
        or a Redis miss/error -- either way, epoch ``0`` is just as valid a namespace as any
        other, it simply starts empty)."""
        raw = await self._cache.get(_epoch_key(company_id))
        if raw is None:
            return 0
        try:
            return int(raw)
        except ValueError:
            return 0

    async def bump_epoch(self, company_id: str) -> None:
        """Invalidate every cached decision for ``company_id``.

        Call this on every write to something a cached decision could have
        depended on: a ``permission_grants`` row created/revoked, or (once
        those fields become mutable through this system) a user's role or
        clearance level.
        """
        result = await self._cache.incr(_epoch_key(company_id))
        if result is None:
            logger.warning("authz epoch bump failed for company_id=%s (Redis unavailable)", company_id)

    async def get(
        self, company_id: str, user_id: str, action: str, resource_type: str, resource_id: Optional[str]
    ) -> Optional[Decision]:
        epoch = await self.current_epoch(company_id)
        raw = await self._cache.get(
            _decision_key(company_id, epoch, user_id, action, resource_type, resource_id)
        )
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return Decision(**payload)

    async def set(
        self,
        company_id: str,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: Optional[str],
        decision: Decision,
    ) -> None:
        if not decision.cacheable:
            return
        epoch = await self.current_epoch(company_id)
        key = _decision_key(company_id, epoch, user_id, action, resource_type, resource_id)
        await self._cache.set(key, json.dumps(asdict(decision)), expire_seconds=_DECISION_TTL_SECONDS)
