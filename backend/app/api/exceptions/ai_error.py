from typing import Any, Dict, Optional

from app.api.exceptions.base import BaseAppException


class AIException(BaseAppException):
    """LLM üretimi veya LangGraph iş akışı yürütmesi başarısız olduğunda fırlatılan istisna."""

    def __init__(
        self,
        message: str = "Yapay zeka iş akışı çalıştırılırken bir hata oluştu.",
        error_code: str = "AI_EXECUTION_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=502,
            details=details,
        )
