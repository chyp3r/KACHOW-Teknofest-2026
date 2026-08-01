from typing import Optional

from pydantic import BaseModel, Field

from app.core.enums.document_type import DocumentType


class RoutingSuggestionRequest(BaseModel):
    """Request a unit-routing decision for a draft, independent of drafting it."""

    draft: str = Field(
        min_length=1, max_length=20000, description="Yönlendirilecek taslak veya evrak metni."
    )
    confidence_score: float = Field(
        default=100.0,
        ge=0.0,
        le=100.0,
        description="Taslağın güven skoru; düşük skorlar insan onayına yönlendirir.",
    )
    document_type: Optional[DocumentType] = Field(
        default=None, description="Bağlam için evrak türü (opsiyonel)."
    )


class RoutingSuggestionResponse(BaseModel):
    """A unit-routing decision."""

    routed_unit: str = Field(description="Önerilen birim.")
    priority: str = Field(description="Öncelik derecesi.")
    reasoning: str = Field(description="Karar gerekçesi.")
    justification: str = Field(description="Karar gerekçesi (API uyumluluğu için ikinci ad).")
