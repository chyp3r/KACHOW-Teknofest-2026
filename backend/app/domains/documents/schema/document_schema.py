from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.ai.compliance.evrak_field import EvrakField, MissingField
from app.ai.verification import InfoQuestion
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.correspondence_type import CorrespondenceType
from app.core.enums.document_type import DocumentType
from app.core.enums.reasoning_level import ReasoningLevel
from app.core.enums.sensitivity_level import SensitivityLevel
from app.shared.validator.storage_path_validator import validate_storage_path


class PiiFindingSchema(BaseModel):
    """One PII pattern match, surfaced without the raw sensitive value.

    ``preview`` is always the redacted form (see ``app.ai.guardrails.pii.
    PiiFinding``) -- this schema crosses the API boundary, so the same rule
    that keeps a raw TCKN/IBAN out of logs and the audit trail applies here.
    """

    kind: str = Field(description="Bulgu türü (örn. 'tckn', 'iban', 'telefon', 'adres').")
    preview: str = Field(description="Maskelenmiş önizleme; ham değer asla döndürülmez.")


class GuardrailAssessmentSchema(BaseModel):
    """Input-side guardrail outcome for one document (see
    ``app.ai.guardrails.sensitivity.assess``)."""

    sensitivity_level: SensitivityLevel = Field(
        default=SensitivityLevel.UNMARKED,
        description="Belgeden çıkarılan veya varsayılan gizlilik derecesi.",
    )
    pii_findings: List[PiiFindingSchema] = Field(
        default_factory=list, description="Tespit edilen kişisel veri bulguları."
    )
    requires_human_review: bool = Field(
        default=False,
        description="Gizlilik derecesi veya bulgular nedeniyle insan onayı gerekip gerekmediği.",
    )
    reasons: List[str] = Field(
        default_factory=list, description="Değerlendirmeyi açıklayan kısa gerekçeler."
    )


class ExtractionInfoSchema(BaseModel):
    """Provenance of the text the analysis was performed on."""

    extractor: str = Field(description="Metni çıkaran bileşen.")
    page_count: int = Field(description="İşlenen sayfa sayısı.")
    char_count: int = Field(description="Çıkarılan karakter sayısı.")
    used_ocr: bool = Field(
        description="Metin OCR ile okunduysa true; alanlar doğrulanmalıdır."
    )
    scrubbed_markers: List[str] = Field(
        default_factory=list,
        description="Metinden temizlenen olası talimat-enjeksiyonu işaretçileri.",
    )


class MevzuatReferenceSchema(BaseModel):
    """A legislation reference suggested for the document."""

    mevzuat: str = Field(description="Mevzuat adı ve varsa madde numarası.")
    aciklama: str = Field(description="Bu hükmün evrakla ilişkisi.")


class DetectedMarkSchema(BaseModel):
    """One region flagged as possibly a signature, stamp, or handwritten
    annotation (see ``app.infrastructure.extractors.marks.DetectedMark``, the
    infrastructure-layer type this mirrors rather than reuses directly --
    same reasoning as ``ExtractionInfoSchema`` not reusing ``ExtractedDocument``).

    A heuristic review hint, not a forensic determination: there is no
    hand-labelled signature/stamp dataset for this project's document
    corpus, so nothing here carries a measured accuracy.
    """

    kind: str = Field(description="'signature', 'stamp' veya 'handwriting'.")
    page: int = Field(description="1 tabanlı sayfa numarası.")
    bbox: tuple[int, int, int, int] = Field(
        description="(x0, y0, x1, y1) -- sayfa boyutundan bağımsız 0-1000 ölçeğinde."
    )
    confidence: float = Field(description="0.0-1.0 arası kaba güven skoru.")


class SignatureAssessmentSchema(BaseModel):
    """Signature/stamp detection outcome for one document -- a review aid,
    never an authoritative substitute for `fields.imza_sahibi` (the typed
    name) or for actually opening the document. See `DetectedMarkSchema`.
    """

    is_signed: bool = Field(
        default=False,
        description="Sayfada en az bir imza şeklinde bölge tespit edildi mi.",
    )
    has_stamp: bool = Field(
        default=False,
        description="Sayfada en az bir mühür/damga şeklinde bölge tespit edildi mi.",
    )
    marks: List[DetectedMarkSchema] = Field(
        default_factory=list, description="Tespit edilen tüm bölgeler."
    )


class DocumentAnalysisResponseSchema(BaseModel):
    """Full first-review (ön inceleme) result for an incoming document.

    Composes the AI-layer contracts (`EvrakField`, `MissingField`) instead of
    restating their fields: they are framework-free Pydantic data models, and
    duplicating fourteen field definitions would create a second source of truth.
    """

    file_name: str = Field(description="Yüklenen dosyanın adı.")
    storage_path: str = Field(description="Ham evrakın saklandığı referans yol.")
    analysis_id: str = Field(
        default="", description="Bu analiz sonucunun kimliği (storage_path ile aynı)."
    )
    extraction: ExtractionInfoSchema = Field(description="Metin çıkarma bilgisi.")
    document_type: DocumentType = Field(description="Belirlenen evrak türü.")
    document_type_label: str = Field(description="Evrak türünün Türkçe adı.")
    summary: str = Field(description="Evrakın kısa Türkçe özeti.")
    #: Defaulted to None, not empty string: distinguishes "never requested"
    #: from "generated but somehow empty", and lets the ~20 on-disk
    #: *_analysis.json caches predating this field keep validating --
    #: get_cached_analysis returns None (-> HTTP 404) on any validation
    #: failure, so this is load-bearing, not decorative (same constraint
    #: that governed `signature` above). Populated on-demand by
    #: DocumentService.generate_detailed_summary, never by analyze_document
    #: itself -- see that method's own docstring for why.
    detailed_summary: Optional[str] = Field(
        default=None,
        description=(
            "İsteğe bağlı ayrıntılı Türkçe özet. Yalnızca kullanıcı özellikle "
            "istediğinde üretilir; üretilmemişse null."
        ),
    )
    fields: EvrakField = Field(description="Evraktan çıkarılan üstveri alanları.")
    missing_fields: List[MissingField] = Field(
        default_factory=list,
        description="Eksik olan zorunlu/önerilen alanlar ve mevzuat atıfları.",
    )
    compliance_status: ComplianceStatus = Field(description="Uygunluk durumu.")
    mevzuat_references: List[MevzuatReferenceSchema] = Field(
        default_factory=list, description="İlgili mevzuat önerileri."
    )
    guardrail: GuardrailAssessmentSchema = Field(
        default_factory=GuardrailAssessmentSchema,
        description="Girdi guardrail değerlendirmesi (gizlilik derecesi, PII bulguları).",
    )
    signature: SignatureAssessmentSchema = Field(
        default_factory=SignatureAssessmentSchema,
        description="İmza/mühür tespit sonucu (bkz. SignatureAssessmentSchema).",
    )


class DocumentFieldsUpdateSchema(BaseModel):
    """Payload for manually correcting a document's extracted fields.

    The full ``EvrakField`` set is replaced wholesale rather than patched
    key-by-key -- the frontend form always round-trips every field it
    rendered (including ones already correctly detected), so a partial
    payload would have no way to distinguish "leave this alone" from "the
    user cleared it".
    """

    fields: EvrakField = Field(description="Kullanıcı tarafından düzeltilmiş üstveri alanları.")


class DraftClassificationSchema(BaseModel):
    """The narrow slice of Görev 1's output the draft flow actually consumes.

    Replaces ``DraftRequestSchema.classification: dict`` (was a free-form,
    unvalidated dict fed straight into prompts -- a correctness hole and an
    injection surface at once).
    """

    document_type: DocumentType = Field(description="Gelen evrakın türü.")
    document_type_label: str = Field(default="", description="Evrak türünün Türkçe adı.")
    summary: str = Field(default="", description="Evrakın kısa Türkçe özeti.")
    fields: EvrakField = Field(default_factory=EvrakField)
    missing_fields: List[MissingField] = Field(default_factory=list)
    mevzuat_references: List[MevzuatReferenceSchema] = Field(default_factory=list)


class DraftRequestSchema(BaseModel):
    """Payload for initiating a drafting and routing workflow."""

    storage_path: str = Field(
        min_length=1,
        max_length=512,
        description="Ham evrakın saklandığı referans yol (Görev 1 çıktısından gelir).",
    )
    classification: DraftClassificationSchema = Field(
        description="Görev 1'den elde edilen belge analiz ve sınıflandırma sonucu."
    )
    instructions: str = Field(
        default="", max_length=4000, description="Opsiyonel kullanıcı talimatı veya prompt eklemesi."
    )
    correspondence_type: CorrespondenceType | None = Field(
        default=None, description="Zorunlu tutulmak istenen yazışma türü."
    )
    reasoning_level: ReasoningLevel = Field(
        default=ReasoningLevel.BALANCED,
        description="Hız/kalite tercihi: fast (hızlı), balanced (dengeli, varsayılan), deep (derin muhakeme).",
    )

    @field_validator("storage_path")
    @classmethod
    def _validate_storage_path(cls, value: str) -> str:
        return validate_storage_path(value)


class DraftResponseSchema(BaseModel):
    """Result of the drafting and routing workflow."""

    draft_id: str = Field(default="", description="Kalıcı taslak kaydının kimliği.")
    draft: str = Field(description="Üretilen nihai resmî yazı taslağı.")
    confidence_score: float = Field(
        description=(
            "Taslak kalitesine verilen güven skoru (0-100), tek bir deterministik "
            "kural tablosundan hesaplanır (bkz. app.ai.verification.confidence_rules) "
            "-- kalite yargıcı skora katılmaz, yalnızca applied_rules üzerinden "
            "insan onayı kapısını açar."
        )
    )
    requires_human_approval: bool = Field(description="İnsan onayı gerektirip gerektirmediği.")
    attempts: int = Field(default=1, description="Taslak üretim/revizyon deneme sayısı.")
    verification: dict = Field(
        default_factory=dict, description="Deterministik doğrulayıcının raporu (VerificationReport)."
    )
    judge: dict = Field(
        default_factory=dict, description="Kalite yargıcının verdiği (varsa) yapılandırılmış değerlendirme."
    )
    missing_information: List[InfoQuestion] = Field(
        default_factory=list,
        description="Taslağı tamamlamak için kullanıcıdan istenen eksik bilgiler.",
    )
    applied_rules: list = Field(
        default_factory=list,
        description=(
            "confidence_score'u üreten kural tablosu satırları -- rule_id/label/"
            "occurrences/penalty_applied/forces_approval (bkz. AppliedRule)."
        ),
    )
    destination: str = Field(description="Evrakın yönlendirildiği birim veya aksiyon.")
    justification: str = Field(description="Yönlendirme kararının gerekçesi.")
