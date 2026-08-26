from typing import Optional

from pydantic import BaseModel, Field

from app.core.enums.compliance_status import ComplianceStatus


class EvrakField(BaseModel):
    """Gelen bir resmi belgenin yapılandırılmış başlık ve imza alanları.

    Her alan isteğe bağlıdır ve varsayılan olarak bilerek None'dır: eksik alan
    tespiti, modelin gerçek yokluğu dürüstçe bildirmesine dayanır. Anlamlı bir
    varsayılan değer verilen bir alan (örneğin "Tasnif Dışı" gizlilik derecesi)
    her belgeyi eksiksiz gösterirdi.
    """

    sayi: Optional[str] = Field(
        default=None,
        description="Belgenin sayısı (örn. 'E-12345678-903-4567'). Yoksa null.",
    )
    tarih: Optional[str] = Field(
        default=None,
        description="Belgenin tarihi, belgede yazıldığı biçimde (örn. '30.07.2026'). Yoksa null.",
    )
    konu: Optional[str] = Field(
        default=None, description="Belgenin konusu. Yoksa null."
    )
    muhatap: Optional[str] = Field(
        default=None,
        description="Belgenin gönderildiği makam veya kişi (örn. 'İLGİLİ MAKAMA'). Yoksa null.",
    )
    gonderen_kurum: Optional[str] = Field(
        default=None,
        description="Belgeyi gönderen idarenin adı (başlık/antet bilgisi). Yoksa null.",
    )
    ilgi: list[str] = Field(
        default_factory=list,
        description="İlgi bölümünde atıf yapılan belgeler. Yoksa boş liste.",
    )
    ekler: list[str] = Field(
        default_factory=list,
        description="Belgenin ek listesinde sayılan belgeler. Yoksa boş liste.",
    )
    imza_sahibi: Optional[str] = Field(
        default=None, description="İmza sahibinin adı ve soyadı. Yoksa null."
    )
    imza_unvani: Optional[str] = Field(
        default=None,
        description="İmza sahibinin unvanı (örn. 'Genel Müdür'). Yoksa null.",
    )
    gizlilik_derecesi: Optional[str] = Field(
        default=None,
        description=(
            "Gizlilik derecesi; yalnızca belgede açıkça yazıyorsa doldur "
            "(örn. 'Hizmete Özel'). Yoksa null."
        ),
    )
    ivedilik: Optional[str] = Field(
        default=None,
        description=(
            "İvedilik durumu; yalnızca belgede açıkça yazıyorsa doldur "
            "(örn. 'ACELE', 'GÜNLÜ'). Yoksa null."
        ),
    )
    basvuran_adi: Optional[str] = Field(
        default=None,
        description="Dilekçe veya başvuruda başvuran kişinin adı ve soyadı. Yoksa null.",
    )
    adres: Optional[str] = Field(
        default=None,
        description="Başvuranın iş veya ikametgâh adresi. Yoksa null.",
    )
    iletisim: Optional[str] = Field(
        default=None,
        description="Telefon veya e-posta gibi iletişim bilgisi. Yoksa null.",
    )
    entities: list[str] = Field(
        default_factory=list,
        description="Belgede geçen önemli varlık isimleri (Kişi, Kurum, Tarih, Para Birimi, Ürün, Referans vb.). Yoksa boş liste.",
    )


class MissingField(BaseModel):
    """Belgede bulunmayan, yasal dayanağıyla birlikte zorunlu bir alan."""

    key: str = Field(description="Eksik alanın teknik adı (örn. 'sayi').")
    label: str = Field(description="Eksik alanın Türkçe adı (örn. 'Sayı').")
    severity: str = Field(
        description="Alanın önemi: 'zorunlu' veya 'onerilen'."
    )
    mevzuat: str = Field(
        description="Alanı zorunlu kılan mevzuat ve madde atfı."
    )
    reason: str = Field(
        description="Alanın neden gerekli olduğunun kısa Türkçe açıklaması."
    )


class ComplianceReport(BaseModel):
    """Bir belgenin alanlarının zorunlu alan kurallarına göre kontrol edilmesinin sonucu."""

    status: ComplianceStatus = Field(description="Belgenin uygunluk durumu.")
    missing_fields: list[MissingField] = Field(
        default_factory=list, description="Eksik olan zorunlu ve önerilen alanlar."
    )
    checked_field_count: int = Field(
        default=0, description="Denetlenen kural sayısı."
    )
