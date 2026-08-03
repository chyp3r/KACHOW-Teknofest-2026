import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Structured logging for HTTP requests/responses, including latency.

    Logs via ``extra={...}`` rather than a pre-formatted f-string: the
    production JSONFormatter reads ``record.__dict__`` for anything beyond
    the standard LogRecord attributes, so fields passed as an f-string were
    invisible to it -- structured logging in name only, one opaque `message`
    string in practice.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        method = request.method
        path = request.url.path
        client_host = request.client.host if request.client else "unknown"

        logger.info(
            "http_request_started",
            extra={"http_method": method, "http_path": path, "http_client": client_host},
        )

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
            "http_request_finished",
            extra={
                "http_method": method,
                "http_path": path,
                "http_status": status_code,
                "duration_ms": response_time,
            },
        )
        return response
