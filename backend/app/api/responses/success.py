from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi.responses import JSONResponse

from app.api.responses.base import APIResponse


def SuccessResponse(
    data: Any = None,
    status_code: int = 200,
    meta: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    """Standartlaştırılmış, birleşik bir başarılı JSONResponse'u döndürmek için yardımcı fonksiyon."""
    meta_info = meta or {}
    if "timestamp" not in meta_info:
        meta_info["timestamp"] = datetime.now(timezone.utc).isoformat()

    response_model = APIResponse(
        success=True, data=data, error=None, meta=meta_info
    )

    return JSONResponse(
        content=response_model.model_dump(), status_code=status_code
    )
