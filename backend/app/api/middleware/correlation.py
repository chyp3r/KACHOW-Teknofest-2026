"""Request correlation IDs.

A ``ContextVar`` rather than ``request.state`` because the value needs to
reach code with no ``Request`` object in scope at all -- workflow node
functions running inside a LangGraph invocation, several calls deep from the
route handler. Contextvars propagate through the async call chain of the same
task automatically; passing the id as an explicit parameter through every
layer between the router and a graph node would touch a lot of signatures for
no benefit over just reading it back out where it's needed.
"""

import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Return the current request's correlation id, or ``"-"`` outside one."""
    return request_id_var.get()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Read or mint a request id and echo it back on the response.

    Registered outermost (added last in ``main.py``, since Starlette applies
    middleware in reverse registration order) so every other middleware and
    every route handler runs with the id already set.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
