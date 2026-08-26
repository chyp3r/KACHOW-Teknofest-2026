from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class CompanyCreate(BaseModel):
    """Yeni bir şirket oluşturmak için Pydantic şeması (yalnızca root)."""

    name: str = Field(min_length=1, max_length=200, description="Şirket adı")
    slug: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
        description="URL/depolama güvenli benzersiz kısa ad (örn. 'acme-holding')",
    )
    tax_number: Optional[str] = Field(default=None, max_length=50, description="Vergi numarası")


class CompanyUpdate(BaseModel):
    """Mevcut bir şirketi güncellemek için Pydantic şeması. Tüm alanlar opsiyoneldir."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    tax_number: Optional[str] = Field(default=None, max_length=50)
    is_active: Optional[bool] = Field(
        default=None, description="False ise şirketin tüm kullanıcıları giriş yapamaz"
    )
    settings: Optional[Dict[str, Any]] = Field(default=None)


class CompanyResponse(BaseModel):
    """Şirket detay çıktısı için Pydantic şeması."""

    id: str = Field(description="Şirket ID")
    name: str = Field(description="Şirket adı")
    slug: str = Field(description="Şirket kısa adı")
    tax_number: Optional[str] = Field(default=None, description="Vergi numarası")
    is_active: bool = Field(description="Şirketin aktif olup olmadığı")
    settings: Dict[str, Any] = Field(default_factory=dict, description="Şirkete özel ayarlar")

    model_config = {"from_attributes": True}


class CompanyAdminAssign(BaseModel):
    """Mevcut bir kullanıcıyı şirket admini olarak atamak için Pydantic şeması."""

    user_id: str = Field(description="Şirket admini yapılacak kullanıcının ID'si")


class CompanyAdapterUpdate(BaseModel):
    """Bir şirketin çalışma zamanı stil adaptörünü elle oluşturmak için
    Pydantic şeması (Faz C2) -- her alanı, eklemek yerine tüm listeyi
    değiştirir.

    Henüz otomatik bir eğitim pipeline'ı yok (Faz C3); böyle biri var
    olana kadar bir admin şirketin adaptörünü bu şekilde yapılandırır.
    """

    style_rules: List[str] = Field(default_factory=list, max_length=20)
    preferred_examples: List[str] = Field(default_factory=list, max_length=10)
    avoided_patterns: List[str] = Field(default_factory=list, max_length=20)


class CompanyAdapterResponse(BaseModel):
    """Bir şirketin mevcut adaptörü için Pydantic şeması -- ``app.ai.
    adapters.company_adapter.CompanyAdapter`` ile alan alan birebir aynıdır."""

    company_id: str
    version: int
    style_rules: List[str]
    preferred_examples: List[str]
    avoided_patterns: List[str]
    trained_at: Optional[str] = None
    sample_count: int


class CompanyProfileUpdate(BaseModel):
    """Bir şirketin kimlik profilini ayarlamak için Pydantic şeması --
    asistanın kendi adı ve şirketin antet/imza sahibi varsayılanı, yazım
    briefi o alanı belirtmeden bıraktığında bir taslağın başlık/imza
    bloğunun geri düştüğü değerlerdir. Her alan, profilin mevcut değerinin
    yerine geçer.
    """

    display_name: str = Field(default="", max_length=200, description="Şirketin tam adı")
    short_name: str = Field(default="", max_length=100, description="Şirketin kısa adı")
    agent_name: str = Field(
        default="", max_length=80, description="Asistanın kendini tanıtırken kullanacağı ad"
    )
    letterhead: str = Field(
        default="", max_length=400, description="Taslakların kullanacağı T.C. kurum anteti"
    )
    default_signer_title: str = Field(
        default="", max_length=100, description="Varsayılan imza unvanı (ör. 'Daire Başkanı')"
    )
    default_signer_name: str = Field(
        default="",
        max_length=150,
        description=(
            "Varsayılan imza sahibi ad soyad -- yazım briefi ve gelen evrakın kendi "
            "imza sahibi alanı boş kaldığında kullanılır. Gelen evrakın imza "
            "sahibiyle ASLA karıştırılmaz; o karşı tarafa aittir."
        ),
    )
    aliases: List[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Şirketin bir belgede veya kullanıcı mesajında geçebilecek diğer ad "
            "biçimleri (kısaltma, eski ad vb.) -- yalnızca bir belgenin bize "
            "gönderildiğini/adımızı taşıdığını tespit etmek için kullanılır, "
            "hiçbir taslakta doğrudan render edilmez."
        ),
    )


class CompanyProfileResponse(BaseModel):
    """Bir şirketin mevcut kimlik profili için Pydantic şeması -- ``app.ai.
    identity.company_profile.CompanyProfile`` ile alan alan birebir aynıdır."""

    company_id: str
    version: int
    display_name: str
    short_name: str
    agent_name: str
    letterhead: str
    default_signer_title: str
    default_signer_name: str = ""
    aliases: List[str] = Field(default_factory=list)
    updated_at: Optional[str] = None


class CompanyRuleItem(BaseModel):
    """Zorunlu/önerilen bir yazım kuralı için Pydantic şeması.

    ``id`` yazarken opsiyoneldir: yeni bir kural için boş bırakılır
    (sunucu kalıcı bir ``Kx`` id atar) ya da aynı kuralı yerinde
    düzenlemek için önceki bir okumanın döndürdüğü id verilir -- bkz.
    ``app.domains.companies.provider.set_company_rules``.
    """

    id: Optional[str] = Field(default=None, max_length=20)
    text: str = Field(min_length=1, max_length=300)
    severity: Literal["zorunlu", "onerilen"] = "zorunlu"
    enabled: bool = True


class CompanyRulesUpdate(BaseModel):
    """Bir şirketin tüm zorunlu kural setini değiştirmek için Pydantic şeması."""

    rules: List[CompanyRuleItem] = Field(default_factory=list, max_length=30)


class CompanyRulesResponse(BaseModel):
    """Bir şirketin mevcut zorunlu kural seti için Pydantic şeması --
    ``app.ai.adapters.company_rules.CompanyRuleSet`` ile alan alan birebir
    aynıdır."""

    company_id: str
    version: int
    rules: List[CompanyRuleItem]
    updated_at: Optional[str] = None
