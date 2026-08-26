from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class SearchParam(BaseModel):
    """Arama sorgusu parametreleri giriş DTO'su."""
    query: str = Field(description="Aranacak metin sorgusu")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Metadata filtre eşlemesi")
    limit: int = Field(default=10, ge=1, le=100, description="Döndürülecek maksimum arama sonucu sayısı")
