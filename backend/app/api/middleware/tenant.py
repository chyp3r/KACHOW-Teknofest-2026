"""Resolve the caller's tenant identity before any DB session is opened.

``app.infrastructure.database.session.get_db`` needs to know the request's
``company_id``/root-ness the moment it opens a session, so it can set the
Postgres GUCs the RLS policies (migration ``0013_rls``) key off of -- but
``get_db`` itself has no access to the request, and ``Depends(get_current_user)``
cannot run first to hand it one: that dependency needs a DB session of its
own to look the user up, which is exactly the session this is trying to
scope. This middleware breaks that cycle by decoding the JWT directly (the
token already carries the ``company_id``/``role`` claims -- see
``AuthService.authenticate_user``) and publishing them to a ``ContextVar``
before the request reaches any dependency at all.

Best-effort and silent on failure by design: a missing or invalid token is
completely normal here (an anonymous request, `/auth/login` itself, or a
request whose real authentication check hasn't run yet) and must not raise
-- that is `get_current_user`/`require_auth_if_enabled`'s job, downstream.
This middleware only ever narrows what a request *can* see; it is never the
thing that decides whether a request is authenticated at all.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import TenantContext, current_tenant_var
from app.core.enums.user_role import UserRole
from app.core.security import decode_token

logger = logging.getLogger(__name__)

_BEARER_PREFIX = "Bearer "


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Publish the JWT's ``company_id``/``role`` claims to ``current_tenant_var``.

    Registered alongside ``CorrelationIdMiddleware`` (see ``app.main``) --
    same ``ContextVar``-token-and-reset shape, so the value is always
    cleared at the end of the request regardless of how it finished.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith(_BEARER_PREFIX):
            raw_token = auth_header[len(_BEARER_PREFIX):]
            try:
                payload = decode_token(raw_token)
            except Exception:
                # Expired/malformed/missing -- not this middleware's problem
                # to report. The request proceeds with no tenant context,
                # which the request-auth dependencies will reject on their
                # own terms if the route actually requires authentication.
                payload = None
            if payload is not None:
                token = current_tenant_var.set(
                    TenantContext(
                        company_id=payload.get("company_id"),
                        is_root=payload.get("role") == UserRole.ROOT.value,
                    )
                )
        try:
            return await call_next(request)
        finally:
            if token is not None:
                current_tenant_var.reset(token)
