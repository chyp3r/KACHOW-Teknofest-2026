from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class APIErrorDetail(BaseModel):
    """APIResponse içindeki yapılandırılmış hata bilgisini temsil eden Pydantic modeli."""

    code: str = Field(
        description="Uygulamaya özgü benzersiz hata kodu (örn. NOT_FOUND, AI_EXECUTION_ERROR)."
    )
    message: str = Field(
        description="Kullanıcı veya geliştirici için okunabilir hata mesajı."
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Ek teknik detaylar veya doğrulama hataları.",
    )
