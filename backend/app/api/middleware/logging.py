import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """SOTA Middleware that performs structured logging for HTTP requests/responses including latency."""

    async def dispatch(self, request: Request, call_next) -> Response:
        method = request.method
        path = request.url.path
        client_host = request.client.host if request.client else "unknown"

        logger.info(f"Incoming request: {method} {path} from {client_host}")

        response = await call_next(request)

        response_time = getattr(request.state, "response_time_ms", 0.0)
        status_code = response.status_code

        log_level = logging.INFO
        if status_code >= 500:
            log_level = logging.ERROR
        elif status_code >= 400:
            log_level = logging.WARNING

        logger.log(
            log_level,
            f"Finished request: {method} {path} - Status: {status_code} - Latency: {response_time}ms",
        )
        return response
