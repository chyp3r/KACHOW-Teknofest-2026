"""Async orchestration wrapping the pure engine with the DB grant store and the Redis cache.

``engine.authorize`` alone only ever sees the built-in rules (see its own
callers in ``documents/router.py``/``drafts/router.py``, which pass no
``grants`` at all) -- this is the layer that actually resolves
``permission_grants`` and makes them count. Anything that needs a
``permission_grants`` row to matter (grant management itself, and any
future resource whose access model is "role rules plus explicit
delegation") goes through ``AuthzService``, not the bare engine function.
"""

from typing import Optional

from app.api.exceptions.authorization import AuthorizationException
from app.core.authz.attributes import Environment, Resource, Subject
from app.core.authz.cache import AuthzDecisionCache
from app.core.authz.engine import Decision, authorize
from app.core.authz.repository import PermissionGrantRepository


class AuthzService:
    """DB- and cache-backed ``authorize()``.

    Args:
        grant_repository: Resolves a subject's currently-active
            ``permission_grants``.
        decision_cache: Optional Redis-backed decision cache. ``None``
            disables caching entirely (every call recomputes) -- used by
            the test suite's autouse fixture (see ``tests/conftest.py``) so
            unit tests never depend on Redis state leaking between them.
    """

    def __init__(
        self,
        grant_repository: PermissionGrantRepository,
        decision_cache: Optional[AuthzDecisionCache] = None,
    ):
        self._grants = grant_repository
        self._cache = decision_cache

    async def authorize(
        self,
        subject: Subject,
        action: str,
        resource: Optional[Resource],
        env: Optional[Environment] = None,
    ) -> Decision:
        """Resolve ``permission_grants`` (cache permitting) and decide.

        ROOT subjects (``subject.company_id is None``) skip grant
        resolution entirely -- ``permission_grants`` rows are always
        company-scoped, so there is nothing to look up for a subject with
        no company. A ROOT subject's decision comes from the tenant gate
        and the built-in wildcard rule alone, same as
        ``engine.authorize`` called with no grants.
        """
        env = env or Environment()
        resource_type = resource.type if resource is not None else "*"
        resource_id = resource.id if resource is not None else None

        if self._cache is not None and subject.company_id is not None:
            cached = await self._cache.get(
                subject.company_id, subject.user_id, action, resource_type, resource_id
            )
            if cached is not None:
                return cached

        grants = ()
        if subject.company_id is not None:
            grants = await self._grants.list_active_for_subject(
                subject.company_id, subject.role, subject.user_id, action
            )

        decision = authorize(subject, action, resource, env, grants)

        if self._cache is not None and subject.company_id is not None:
            await self._cache.set(
                subject.company_id, subject.user_id, action, resource_type, resource_id, decision
            )

        return decision

    async def invalidate_company(self, company_id: str) -> None:
        """Bump the decision-cache epoch for ``company_id``.

        Call after any write to something a cached decision could depend
        on -- creating or revoking a ``permission_grants`` row, today's only
        writer (see ``users/router.py``'s grant-management endpoints). A
        no-op when caching is disabled (``self._cache is None``, the test
        default -- see ``tests/conftest.py``).
        """
        if self._cache is not None:
            await self._cache.bump_epoch(company_id)

    async def authorize_or_raise(
        self,
        subject: Subject,
        action: str,
        resource: Optional[Resource],
        env: Optional[Environment] = None,
    ) -> None:
        """``authorize()``, raising ``AuthorizationException`` on a deny."""
        decision = await self.authorize(subject, action, resource, env)
        if not decision.permit:
            raise AuthorizationException(message="Bu işlem için yetkiniz yok.")
