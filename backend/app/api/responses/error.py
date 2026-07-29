from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi.responses import JSONResponse

from app.api.responses.base import APIResponse
from app.api.responses.error_detail import APIErrorDetail


def ErrorResponse(
    code: str,
    message: str,
    status_code: int = 400,
    details: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    """Helper to return a standardized unified error JSONResponse."""
    meta_info = meta or {}
    if "timestamp" not in meta_info:
        meta_info["timestamp"] = datetime.now(timezone.utc).isoformat()

    error_detail = APIErrorDetail(code=code, message=message, details=details)

    response_model = APIResponse(
        success=False, data=None, error=error_detail, meta=meta_info
    )

    return JSONResponse(
        content=response_model.model_dump(), status_code=status_code
    )
