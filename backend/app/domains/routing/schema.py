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
        description=(
            "Taslağın güven skoru; düşük skorlarda birim önerisi yine de yapılır, ancak "
            "requires_human_approval=True ile işaretlenir."
        ),
    )
    document_type: Optional[DocumentType] = Field(
        default=None, description="Bağlam için evrak türü (opsiyonel)."
    )


class RoutingSuggestionResponse(BaseModel):
    """A unit-routing decision."""

    routed_unit: Optional[str] = Field(
        default=None,
        description=(
            "Önerilen birim; şirkette hiç aktif birim tanımlı değilse (bkz. "
            "requires_human_approval) null olabilir, aksi halde her zaman doludur."
        ),
    )
    alternative_units: list[str] = Field(
        default_factory=list,
        description="Birincil öneriye alternatif olabilecek ikinci en uygun birim(ler).",
    )
    priority: str = Field(description="Öncelik derecesi.")
    reasoning: str = Field(description="Karar gerekçesi.")
    justification: str = Field(description="Karar gerekçesi (API uyumluluğu için ikinci ad).")
    requires_human_approval: bool = Field(
        default=False,
        description=(
            "True ise öneri düşük güvenle (veya hiç birim tanımlı değilken) yapıldı; "
            "gözden geçirilmesi önerilir. Öneriyi engellemez, yalnızca denetim/loglama içindir."
        ),
    )
