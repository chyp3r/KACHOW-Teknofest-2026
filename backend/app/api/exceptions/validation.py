from typing import Any, Dict, Optional

from app.api.exceptions.base import BaseAppException


class ValidationException(BaseAppException):
    """Exception raised when payload validation fails."""

    def __init__(
        self,
        message: str = "Invalid request data.",
        error_code: str = "VALIDATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=422,
            details=details,
        )
