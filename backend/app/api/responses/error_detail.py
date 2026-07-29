from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class APIErrorDetail(BaseModel):
    """Pydantic model representing structured error information in APIResponse."""

    code: str = Field(
        description="Uygulamaya özel benzersiz hata kodu (örn. NOT_FOUND, AI_EXECUTION_ERROR)."
    )
    message: str = Field(
        description="Kullanıcıya veya geliştiriciye gösterilecek açıklayıcı hata mesajı."
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Hata hakkında ek teknik detaylar veya validasyon hataları.",
    )
