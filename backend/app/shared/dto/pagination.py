from typing import Generic, List, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")

class PaginationParam(BaseModel):
    """Sayfalama parametreleri giriş DTO'su."""
    page: int = Field(default=1, ge=1, description="1'den başlayan sayfa numarası")
    size: int = Field(default=20, ge=1, le=100, description="Sayfa başına öğe sayısı")

    @property
    def offset(self) -> int:
        """SQL sorgu offset değerini hesaplar."""
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        """size için takma ad."""
        return self.size

class PaginatedResponse(BaseModel, Generic[T]):
    """Sayfalanmış yanıt yapısını saran DTO."""
    items: List[T] = Field(description="Mevcut sayfadaki öğelerin listesi")
    total: int = Field(description="Tüm sayfalardaki toplam öğe sayısı")
    page: int = Field(description="Mevcut sayfa numarası")
    size: int = Field(description="Sayfa başına öğe sayısı")
    pages: int = Field(description="Toplam sayfa sayısı")
