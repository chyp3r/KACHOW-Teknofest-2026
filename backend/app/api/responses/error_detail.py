from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class APIErrorDetail(BaseModel):
    """Pydantic model representing structured error information in APIResponse."""

    code: str = Field(
        description="Application-specific unique error code (e.g. NOT_FOUND, AI_EXECUTION_ERROR)."
    )
    message: str = Field(
        description="Human-readable error message for the user or developer."
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional technical details or validation errors.",
    )
