from typing import Any, Dict, Optional

from app.api.exceptions.base import BaseAppException


class AuthorizationException(BaseAppException):
    """Erişim reddedildiğinde fırlatılan istisna."""

    def __init__(
        self,
        message: str = "Bu işlemi gerçekleştirmek için yetkiniz yok.",
        error_code: str = "PERMISSION_DENIED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=403,
            details=details,
        )
