from datetime import datetime, timezone
from typing import Any, Dict, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

from app.api.responses.error_detail import APIErrorDetail

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Standardized unified SOTA API Response wrapper for all endpoints."""

    success: bool = Field(description="İşlemin başarı durumu.")
    data: Optional[T] = Field(
        default=None, description="Başarılı işlem sonucunda dönen veri."
    )
    error: Optional[APIErrorDetail] = Field(
        default=None,
        description="Hata durumunda dönen yapılandırılmış hata detayları.",
    )
    meta: Dict[str, Any] = Field(
        default_factory=lambda: {
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        description="Yanıt ile ilgili meta bilgiler (örn. yanıt süresi, zaman damgası).",
    )
