from app.api.exceptions.base import BaseAppException


class RateLimitException(BaseAppException):
    """Bir istemci izin verilen istek sınırını aştığında fırlatılan istisna."""

    def __init__(self, message: str = "Çok fazla istek gönderildi. Lütfen bir süre bekleyip tekrar deneyin."):
        super().__init__(
            message=message,
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=429,
        )
