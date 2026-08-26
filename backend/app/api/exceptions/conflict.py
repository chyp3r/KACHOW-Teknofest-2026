from typing import Any, Dict, Optional

from app.api.exceptions.base import BaseAppException


class ConflictException(BaseAppException):
    """Bir kaynak çakışması oluştuğunda fırlatılan istisna."""

    def __init__(
        self,
        message: str = "Bir çakışma oluştu.",
        error_code: str = "RESOURCE_CONFLICT",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=409,
            details=details,
        )
