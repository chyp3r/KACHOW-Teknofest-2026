"""FastAPI-facing glue: ``UserModel`` -> ``Subject``, and the PEP #1 dependency factory.

``app.api.dependency`` stays the single place every router imports its
`Depends(...)` callables from (see that module) -- ``require_permission``
is re-exported there rather than routers importing straight from this
package, same as every other dependency factory.
"""

from typing import Awaitable, Callable, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.attributes import Resource, Subject
from app.core.authz.cache import AuthzDecisionCache
from app.core.authz.repository import PermissionGrantRepository
from app.core.authz.service import AuthzService
from app.core.enums.user_role import UserRole
from app.domains.users.model.user_model import UserModel
from app.infrastructure.cache import get_cache
from app.infrastructure.database.session import get_db

#: Loads the resource a permission check needs, given the caller and a DB
#: session. Returns ``None`` for a resource-less/creation-time check.
ResourceLoader = Callable[[UserModel, AsyncSession], Awaitable[Optional[Resource]]]


def subject_from_user(user: UserModel) -> Subject:
    """Build the PDP's ``Subject`` from an authenticated ``UserModel``.

    An unrecognised ``user.role`` string (data corruption, or a role value
    retired from ``UserRole`` with rows never migrated) resolves to
    ``UserRole.EMPLOYEE`` rather than raising -- the same fail-toward
    -least-privilege choice ``app.core.permissions.role_checker.
    clearance_for`` makes for the same situation: EMPLOYEE's built-in rules
    are ``scope="own"`` only, so this can never grant more than "the caller
    may act on resources it owns", which is the narrowest the engine's rule
    table expresses.
    """
    try:
        role = UserRole(user.role)
    except ValueError:
        role = UserRole.EMPLOYEE
    return Subject(user_id=user.id, role=role, company_id=user.company_id)


def get_authz_service(db: AsyncSession = Depends(get_db)) -> AuthzService:
    """Provide a DB- and Redis-cache-backed ``AuthzService``.

    Overridden in tests (see ``tests/conftest.py``'s autouse fixture) to a
    cache-less instance backed by whatever ``get_db`` override is already in
    effect, so a test that never heard of ``permission_grants`` still gets
    "no grants, built-in rules only" rather than a real DB round trip.
    """
    return AuthzService(
        grant_repository=PermissionGrantRepository(db),
        decision_cache=AuthzDecisionCache(get_cache()),
    )


def require_permission(action: str, resource_loader: Optional[ResourceLoader] = None):
    """Dependency factory: permit only callers ``authorize()`` grants ``action`` to.

    The PEP #1 counterpart to the ownership checks inlined in
    ``documents/router.py``/``drafts/router.py`` (PEP #2, using the bare
    ``engine.authorize`` with no DB grants -- see those routers). This one
    is for routes whose access model is exactly "built-in role rules plus
    whatever ``permission_grants`` say", most notably the grant-management
    endpoints themselves.

    Args:
        action: An ``Action`` constant.
        resource_loader: Optional async callable resolving the target
            resource from the caller and a DB session. Omitted for
            resource-less checks.

    Returns:
        A FastAPI dependency yielding the authenticated user once permitted.
    """
    from app.api.dependency import get_current_user

    async def _check(
        current_user: UserModel = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        authz: AuthzService = Depends(get_authz_service),
    ) -> UserModel:
        resource = await resource_loader(current_user, db) if resource_loader is not None else None
        await authz.authorize_or_raise(subject_from_user(current_user), action, resource)
        return current_user

    return _check
