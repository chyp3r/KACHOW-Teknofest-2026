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
    """Ham hassas değer olmadan sunulan bir PII kalıp eşleşmesi.

    ``preview`` her zaman sansürlenmiş formdur (bkz. ``app.ai.guardrails.pii.
    PiiFinding``) -- bu şema API sınırını geçtiği için, ham bir TCKN/IBAN'ı
    loglardan ve denetim izinden uzak tutan aynı kural burada da geçerlidir.
    """

    kind: str = Field(description="Bulgu türü (örn. 'tckn', 'iban', 'telefon', 'adres').")
    preview: str = Field(description="Maskelenmiş önizleme; ham değer asla döndürülmez.")


class GuardrailAssessmentSchema(BaseModel):
    """Bir evrak için girdi tarafı guardrail sonucu (bkz.
    ``app.ai.guardrails.sensitivity.assess``)."""

    sensitivity_level: SensitivityLevel = Field(
        default=SensitivityLevel.UNMARKED,
        description=(
            "Belgeden çıkarılan HAM gizlilik derecesi -- belgede hiç damga "
            "yoksa 'unmarked'. Fiilen uygulanan derece için "
            "effective_sensitivity_level'a bak."
        ),
    )
    effective_sensitivity_level: SensitivityLevel = Field(
        default=SensitivityLevel.UNMARKED,
        description=(
            "Erişim denetiminde fiilen kullanılan derece -- sensitivity_level "
            "'unmarked' ise politika gereği en düşük dereceye otomatik "
            "atanır (sensitivity_is_defaulted=true olur), aksi halde "
            "sensitivity_level ile aynıdır."
        ),
    )
    sensitivity_is_defaulted: bool = Field(
        default=False,
        description=(
            "effective_sensitivity_level, belgede hiç gizlilik damgası "
            "olmadığı için varsayılan olarak atandıysa true."
        ),
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
    """Analizin üzerinde yapıldığı metnin kaynağı."""

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
    """Evrak için önerilen bir mevzuat atfı."""

    mevzuat: str = Field(description="Mevzuat adı ve varsa madde numarası.")
    aciklama: str = Field(description="Bu hükmün evrakla ilişkisi.")


class DetectedMarkSchema(BaseModel):
    """Muhtemelen bir imza, mühür veya el yazısı not olarak işaretlenmiş bir
    bölge (bkz. ``app.infrastructure.extractors.marks.DetectedMark``; bu
    şema o altyapı katmanı tipini doğrudan yeniden kullanmak yerine
    yansıtır -- ``ExtractionInfoSchema``'nın ``ExtractedDocument``'ı yeniden
    kullanmamasıyla aynı mantık).

    Adli bir tespit değil, sezgisel bir inceleme ipucudur: bu projenin
    evrak külliyatı için elle etiketlenmiş bir imza/mühür veri kümesi
    yoktur, bu yüzden buradaki hiçbir değer ölçülmüş bir doğruluk taşımaz.
    """

    kind: str = Field(description="'signature', 'stamp' veya 'handwriting'.")
    page: int = Field(description="1 tabanlı sayfa numarası.")
    bbox: tuple[int, int, int, int] = Field(
        description="(x0, y0, x1, y1) -- sayfa boyutundan bağımsız 0-1000 ölçeğinde."
    )
    confidence: float = Field(description="0.0-1.0 arası kaba güven skoru.")


class SignatureAssessmentSchema(BaseModel):
    """Bir evrak için imza/mühür tespit sonucu -- bir inceleme yardımcısıdır,
    `fields.imza_sahibi`'nin (tipli isim) veya evrakı fiilen açmanın yerine
    asla yetkili bir alternatif değildir. Bkz. `DetectedMarkSchema`.
    """

    is_signed: Optional[bool] = Field(
        default=None,
        description=(
            "Sayfada en az bir imza şeklinde bölge tespit edildi mi. "
            "None: tespit hiç çalışmadı (belge rasterize edilmedi, ör. "
            "doğrudan metin katmanından okunan bir PDF) -- bilinmiyor, "
            "imzasız değil. False: tespit çalıştı ve hiçbir imza bölgesi "
            "bulamadı."
        ),
    )
    has_stamp: Optional[bool] = Field(
        default=None,
        description=(
            "Sayfada en az bir mühür/damga şeklinde bölge tespit edildi mi. "
            "Aynı None/False ayrımı is_signed ile aynıdır."
        ),
    )
    marks: List[DetectedMarkSchema] = Field(
        default_factory=list, description="Tespit edilen tüm bölgeler."
    )


class DocumentAnalysisResponseSchema(BaseModel):
    """Gelen bir evrak için tam ön inceleme sonucu.

    Alanlarını yeniden yazmak yerine AI katmanı sözleşmelerini (`EvrakField`,
    `MissingField`) bir araya getirir: bunlar framework'ten bağımsız Pydantic
    veri modelleridir ve on dört alan tanımını tekrarlamak ikinci bir gerçek
    kaynağı yaratırdı.
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
    #: Boş string değil None olarak varsayılır: "hiç istenmedi" ile
    #: "üretildi ama bir şekilde boş"u ayırt eder ve bu alandan önce var
    #: olan diskteki ~20 *_analysis.json önbelleğinin doğrulanmaya devam
    #: etmesini sağlar -- get_cached_analysis herhangi bir doğrulama
    #: hatasında None döner (-> HTTP 404), bu yüzden bu süslemeden çok
    #: işlevseldir (yukarıdaki `signature` için geçerli olan aynı kısıt).
    #: DocumentService.generate_detailed_summary tarafından isteğe bağlı
    #: doldurulur, analyze_document'ın kendisi tarafından asla -- neden
    #: olduğu için o metodun kendi docstring'ine bakın.
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
    """Bir evrakın çıkarılan alanlarını elle düzeltmek için gövde.

    Tam ``EvrakField`` kümesi anahtar anahtar yamalanmak yerine bütünüyle
    değiştirilir -- ön yüz formu render ettiği her alanı (zaten doğru
    tespit edilenler dahil) her zaman geri gönderir, bu yüzden kısmi bir
    gövdenin "buna dokunma" ile "kullanıcı temizledi"yi ayırt etmesinin
    hiçbir yolu olmazdı.
    """

    fields: EvrakField = Field(description="Kullanıcı tarafından düzeltilmiş üstveri alanları.")


class DocumentTextSchema(BaseModel):
    """Daha önce analiz edilmiş bir evrakın çıkarılmış/OCR edilmiş metni.

    "OCR metnini görüntüle ve düzelt" panel bölümünü destekler. Bilerek
    ``DocumentAnalysisResponseSchema``'ya bir alan olarak eklenmek yerine
    ondan ayrı tutulur: o şema, analiz önbelleğinin ``"analysis"`` anahtarı
    altında olduğu gibi kalıcı hale getirilir ve her evrak-listesi
    seçiminde yeniden gönderilir, bu yüzden binlerce karakterlik metni ona
    asmak evrak başına metni iki kez saklamak (bkz.
    ``DocumentService._save_document_analysis_cache``, ``extracted_text``/
    ``pages``'i zaten kardeş anahtarlar olarak kalıcı hale getiriyor) ve bu
    aktarım maliyetini her ilgisiz okumada ödemek anlamına gelirdi.
    """

    pages: List[str] = Field(description="Sayfa sayfa çıkarılan/OCR edilmiş metin.")
    extracted_text: str = Field(description="Sayfaların birleştirilmiş hali.")
    page_count: int = Field(description="Sayfa sayısı.")
    extractor: str = Field(description="Metni çıkaran bileşen (örn. 'tesseract', 'ollama_vision').")
    used_ocr: bool = Field(description="Metin OCR ile okunduysa true.")


#: Elle düzeltilmiş sayfa metni için sayfa başına ve toplam üst sınırlar.
#: Gerçek bir resmi yazışma sayfasına göre cömerttir -- bu projenin kendi
#: külliyatındaki en uzun gerçek evrak (CY-034) 5 sayfa boyunca ~10.664
#: karakterdir -- ama yine de tek bir isteğin gövde boyutunu sınırlar.
#: Yukarıdaki DraftRequestSchema.instructions'ın max_length emsalini izler.
MAX_TEXT_PAGE_LENGTH = 20_000
MAX_TEXT_TOTAL_LENGTH = 100_000


class DocumentTextUpdateSchema(BaseModel):
    """Elle düzeltilmiş OCR/çıkarılan metni kaydetmek için gövde.

    Yalnızca ``pages`` taşır, birleştirilmiş bir ``extracted_text`` asla
    taşımaz -- sunucu birleşimi her zaman gönderilen sayfalardan yeniden
    türetir (bkz. ``DocumentService.update_document_text``).
    ``"\\n\\n".join(pages)``'in kayıpsız bir tersi yoktur (çift boşluklu bir
    kaynak sayfa geri bölündüğünde başladığından çok daha fazla parçaya
    ayrılır), bu yüzden istemcinin gönderdiği birleştirilmiş metni kabul
    etmek, sayfaların fiilen söylediğinden sessizce sapma riski taşırdı.
    Sunucu ayrıca önbellekteki evrakla eşleşmeyen bir sayfa sayısını
    reddeder, çünkü ``PageMap``, ``get_document_outline``/
    ``get_document_section`` ve ``signature.marks[].page`` hepsi sayfa
    numarasına göre indekslenir.
    """

    pages: List[str] = Field(
        min_length=1,
        description="Düzeltilmiş sayfa metinleri; sayfa sayısı önbellekteki belgeyle eşleşmelidir.",
    )

    @field_validator("pages")
    @classmethod
    def _validate_page_lengths(cls, value: List[str]) -> List[str]:
        for page in value:
            if len(page) > MAX_TEXT_PAGE_LENGTH:
                raise ValueError(
                    f"Sayfa metni {MAX_TEXT_PAGE_LENGTH} karakteri aşamaz."
                )
        if sum(len(page) for page in value) > MAX_TEXT_TOTAL_LENGTH:
            raise ValueError(f"Toplam metin {MAX_TEXT_TOTAL_LENGTH} karakteri aşamaz.")
        return value


class DraftClassificationSchema(BaseModel):
    """Görev 1'in çıktısının taslak akışının fiilen tükettiği dar dilimi.

    ``DraftRequestSchema.classification: dict``'in yerini alır (doğrudan
    prompt'lara beslenen serbest biçimli, doğrulanmamış bir dict idi --
    aynı anda hem bir doğruluk açığı hem bir enjeksiyon yüzeyi).
    """

    document_type: DocumentType = Field(description="Gelen evrakın türü.")
    document_type_label: str = Field(default="", description="Evrak türünün Türkçe adı.")
    summary: str = Field(default="", description="Evrakın kısa Türkçe özeti.")
    fields: EvrakField = Field(default_factory=EvrakField)
    missing_fields: List[MissingField] = Field(default_factory=list)
    mevzuat_references: List[MevzuatReferenceSchema] = Field(default_factory=list)


class DraftRequestSchema(BaseModel):
    """Taslak oluşturma ve yönlendirme iş akışını başlatmak için gövde."""

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
    """Taslak oluşturma ve yönlendirme iş akışının sonucu."""

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
    alternative_units: List[str] = Field(
        default_factory=list,
        description="Birincil öneriye alternatif olabilecek ikinci en uygun birim(ler).",
    )
    justification: str = Field(description="Yönlendirme kararının gerekçesi.")
