from typing import Any, Dict, Optional

from app.api.exceptions.base import BaseAppException


class NotFoundException(BaseAppException):
    """Exception raised when a resource is not found."""

    def __init__(
        self,
        message: str = "Aranan kaynak bulunamadı.",
        error_code: str = "NOT_FOUND",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=404,
            details=details,
        )
