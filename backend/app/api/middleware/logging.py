import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Gecikme dahil olmak üzere HTTP istek/yanıtları için yapılandırılmış (structured) loglama.

    Önceden biçimlendirilmiş bir f-string yerine ``extra={...}`` üzerinden
    loglar: üretimdeki JSONFormatter, standart LogRecord özniteliklerinin
    ötesindeki her şey için ``record.__dict__``'i okur, bu yüzden f-string
    olarak geçirilen alanlar onun için görünmezdi -- pratikte sadece isimde
    var olan yapılandırılmış loglama, tek bir opak `message` string'inden
    ibaret kalırdı.
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
