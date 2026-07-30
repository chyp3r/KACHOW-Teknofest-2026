from app.api.exceptions.base import BaseAppException


class RateLimitException(BaseAppException):
    """Exception raised when a client exceeds the allowed rate limit."""

    def __init__(self, message: str = "Too many requests. Please wait a moment and try again."):
        super().__init__(
            message=message,
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=429,
        )
