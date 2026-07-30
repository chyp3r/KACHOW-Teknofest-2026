from pydantic import BaseModel, Field
from typing import List

from app.ai.compliance.evrak_field import EvrakField, MissingField
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType

class DocumentUploadSchema(BaseModel):
    filename: str

class DocumentClassificationSchema(BaseModel):
    document_id: str
    document_type: str
    confidence: float

class DocumentAnalysisSchema(BaseModel):
    document_id: str
    extracted_entities: List[str]
    missing_info: List[str]
    recommended_rules: List[str]
    summary: str

class DraftRequestSchema(BaseModel):
    """Payload for initiating a drafting and routing workflow."""

    storage_path: str = Field(description="Ham evrakın saklandığı referans yol (Görev 1 çıktısından gelir).")
    classification: dict = Field(description="Görev 1'den elde edilen belge analiz ve sınıflandırma sonucu (EvrakField dahil).")
    instructions: str = Field(default="", description="Opsiyonel kullanıcı talimatı veya prompt eklemesi.")
    correspondence_type: str | None = Field(default=None, description="Zorunlu tutulmak istenen yazışma türü (örn. 'cover_letter').")


class DraftResponseSchema(BaseModel):
    """Result of the drafting and routing workflow."""

    draft: str = Field(description="Üretilen nihai resmî yazı taslağı.")
    confidence_score: float = Field(description="Taslak kalitesine verilen güven skoru (0-100).")
    requires_human_approval: bool = Field(description="İnsan onayı gerektirip gerektirmediği (eksik bilgi vb. durumlar).")
    destination: str = Field(description="Evrakın yönlendirildiği birim (HR, Legal vb.) veya aksiyon.")
    justification: str = Field(description="Yönlendirme kararının gerekçesi.")


class ExtractionInfoSchema(BaseModel):
    """Provenance of the text the analysis was performed on."""

    extractor: str = Field(description="Metni çıkaran bileşen.")
    page_count: int = Field(description="İşlenen sayfa sayısı.")
    char_count: int = Field(description="Çıkarılan karakter sayısı.")
    used_ocr: bool = Field(
        description="Metin OCR ile okunduysa true; alanlar doğrulanmalıdır."
    )


class MevzuatReferenceSchema(BaseModel):
    """A legislation reference suggested for the document."""

    mevzuat: str = Field(description="Mevzuat adı ve varsa madde numarası.")
    aciklama: str = Field(description="Bu hükmün evrakla ilişkisi.")


class DocumentAnalysisResponseSchema(BaseModel):
    """Full first-review (ön inceleme) result for an incoming document.

    Composes the AI-layer contracts (`EvrakField`, `MissingField`) instead of
    restating their fields: they are framework-free Pydantic data models, and
    duplicating fourteen field definitions would create a second source of truth.
    """

    file_name: str = Field(description="Yüklenen dosyanın adı.")
    storage_path: str = Field(description="Ham evrakın saklandığı referans yol.")
    extraction: ExtractionInfoSchema = Field(description="Metin çıkarma bilgisi.")
    document_type: DocumentType = Field(description="Belirlenen evrak türü.")
    document_type_label: str = Field(description="Evrak türünün Türkçe adı.")
    summary: str = Field(description="Evrakın kısa Türkçe özeti.")
    fields: EvrakField = Field(description="Evraktan çıkarılan üstveri alanları.")
    missing_fields: List[MissingField] = Field(
        default_factory=list,
        description="Eksik olan zorunlu/önerilen alanlar ve mevzuat atıfları.",
    )
    compliance_status: ComplianceStatus = Field(description="Uygunluk durumu.")
    mevzuat_references: List[MevzuatReferenceSchema] = Field(
        default_factory=list, description="İlgili mevzuat önerileri."
    )
