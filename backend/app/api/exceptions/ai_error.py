from typing import Any, Dict, Optional

from app.api.exceptions.base import BaseAppException


class AIException(BaseAppException):
    """Exception raised when LLM generation or LangGraph workflow execution fails."""

    def __init__(
        self,
        message: str = "An error occurred while executing the AI workflow.",
        error_code: str = "AI_EXECUTION_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=502,
            details=details,
        )
