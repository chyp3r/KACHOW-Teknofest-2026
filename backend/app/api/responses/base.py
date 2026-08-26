from datetime import datetime, timezone
from typing import Any, Dict, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

from app.api.responses.error_detail import APIErrorDetail

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Tüm endpoint'ler için standartlaştırılmış, birleşik SOTA API yanıt sarmalayıcısı."""

    success: bool = Field(description="İşlemin başarılı olup olmadığını belirtir.")
    data: Optional[T] = Field(
        default=None, description="Başarılı bir işlemde döndürülen payload."
    )
    error: Optional[APIErrorDetail] = Field(
        default=None,
        description="Hata durumunda döndürülen yapılandırılmış hata bilgisi.",
    )
    meta: Dict[str, Any] = Field(
        default_factory=lambda: {
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        description="Yanıt meta verisi (örn. yanıt süresi, zaman damgası).",
    )
