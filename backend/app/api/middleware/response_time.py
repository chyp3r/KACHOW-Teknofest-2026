import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class ResponseTimeMiddleware(BaseHTTPMiddleware):
    """SOTA Middleware that measures HTTP response processing time and appends it to response headers."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()

        response = await call_next(request)

        process_time = time.perf_counter() - start_time
        response_time_ms = round(process_time * 1000, 2)

        # Store in request state for downstream logging/handlers
        request.state.response_time_ms = response_time_ms

        response.headers["X-Response-Time-Ms"] = str(response_time_ms)
        return response
