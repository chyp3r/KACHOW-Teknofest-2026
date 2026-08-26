from typing import Any, Dict, Optional

from app.api.exceptions.base import BaseAppException


class AuthenticationException(BaseAppException):
    """Kimlik doğrulama başarısız olduğunda fırlatılan istisna."""

    def __init__(
        self,
        message: str = "Kimlik doğrulama başarısız oldu.",
        error_code: str = "AUTHENTICATION_FAILED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=401,
            details=details,
        )
