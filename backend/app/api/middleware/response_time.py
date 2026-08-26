import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class ResponseTimeMiddleware(BaseHTTPMiddleware):
    """HTTP yanıt işleme süresini ölçen ve yanıt başlıklarına ekleyen SOTA middleware."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()

        response = await call_next(request)

        process_time = time.perf_counter() - start_time
        response_time_ms = round(process_time * 1000, 2)

        # Sonraki loglama/handler'lar için request state'e kaydet
        request.state.response_time_ms = response_time_ms

        response.headers["X-Response-Time-Ms"] = str(response_time_ms)
        return response
