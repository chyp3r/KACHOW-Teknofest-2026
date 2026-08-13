"""Request-scoped tenant context, propagated via a ``ContextVar``.

Same rationale as ``app.api.middleware.correlation``'s ``request_id_var``: the
value needs to reach ``app.infrastructure.database.session.get_db``, which
has no ``Request`` object in scope, and a ``ContextVar`` propagates through
the async call chain of the same task automatically -- threading it through
every dependency signature between the middleware and ``get_db`` would touch
a lot of code for no benefit over just reading it back out where it's needed.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TenantContext:
    """The tenant identity resolved from the current request's JWT, if any.

    Attributes:
        company_id: The caller's company, or ``None`` for a ``UserRole.ROOT``
            subject (which has none -- see ``UserModel.company_id``'s
            docstring) or when no valid token was present at all.
        is_root: Whether the caller's JWT ``role`` claim is ``"root"`` --
            drives the ``app.is_root`` Postgres GUC, which the RLS policies
            added in migration ``0013_rls`` OR into their ``company_id``
            comparison so a scoped-in root subject can cross companies.
    """

    company_id: Optional[str]
    is_root: bool


current_tenant_var: ContextVar[Optional[TenantContext]] = ContextVar("current_tenant", default=None)


def get_current_tenant() -> Optional[TenantContext]:
    """The current request's resolved tenant context, or ``None``.

    ``None`` covers both "no request in flight" and "a request with no
    valid JWT" (an anonymous call, or one whose token failed to decode) --
    callers that care about the difference don't exist today, since every
    reader (``app.infrastructure.database.session.get_db``) treats both
    identically: no company, no root bypass, RLS returns zero rows on every
    tenant-scoped table until a real identity is established.
    """
    return current_tenant_var.get()
