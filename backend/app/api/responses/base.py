from datetime import datetime, timezone
from typing import Any, Dict, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

from app.api.responses.error_detail import APIErrorDetail

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Standardized unified SOTA API Response wrapper for all endpoints."""

    success: bool = Field(description="Indicates whether the operation was successful.")
    data: Optional[T] = Field(
        default=None, description="Payload returned on a successful operation."
    )
    error: Optional[APIErrorDetail] = Field(
        default=None,
        description="Structured error details returned on failure.",
    )
    meta: Dict[str, Any] = Field(
        default_factory=lambda: {
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        description="Response metadata (e.g., response time, timestamp).",
    )
