from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class CompanyCreate(BaseModel):
    """Pydantic schema for creating a new company (root only)."""

    name: str = Field(min_length=1, max_length=200, description="Şirket adı")
    slug: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
        description="URL/depolama güvenli benzersiz kısa ad (örn. 'acme-holding')",
    )
    tax_number: Optional[str] = Field(default=None, max_length=50, description="Vergi numarası")


class CompanyUpdate(BaseModel):
    """Pydantic schema for updating an existing company. All fields optional."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    tax_number: Optional[str] = Field(default=None, max_length=50)
    is_active: Optional[bool] = Field(
        default=None, description="False ise şirketin tüm kullanıcıları giriş yapamaz"
    )
    settings: Optional[Dict[str, Any]] = Field(default=None)


class CompanyResponse(BaseModel):
    """Pydantic schema for company details output."""

    id: str = Field(description="Şirket ID")
    name: str = Field(description="Şirket adı")
    slug: str = Field(description="Şirket kısa adı")
    tax_number: Optional[str] = Field(default=None, description="Vergi numarası")
    is_active: bool = Field(description="Şirketin aktif olup olmadığı")
    settings: Dict[str, Any] = Field(default_factory=dict, description="Şirkete özel ayarlar")

    model_config = {"from_attributes": True}


class CompanyAdminAssign(BaseModel):
    """Pydantic schema for assigning an existing user as a company admin."""

    user_id: str = Field(description="Şirket admini yapılacak kullanıcının ID'si")


class CompanyAdapterUpdate(BaseModel):
    """Pydantic schema for hand-authoring a company's runtime style adapter
    (Faz C2) -- replaces the whole list per field, not an append.

    There is no automated training pipeline yet (Faz C3); this is how an
    admin configures a company's adapter until one exists.
    """

    style_rules: List[str] = Field(default_factory=list, max_length=20)
    preferred_examples: List[str] = Field(default_factory=list, max_length=10)
    avoided_patterns: List[str] = Field(default_factory=list, max_length=20)


class CompanyAdapterResponse(BaseModel):
    """Pydantic schema for one company's current adapter -- mirrors
    ``app.ai.adapters.company_adapter.CompanyAdapter`` field-for-field."""

    company_id: str
    version: int
    style_rules: List[str]
    preferred_examples: List[str]
    avoided_patterns: List[str]
    trained_at: Optional[str] = None
    sample_count: int


class CompanyProfileUpdate(BaseModel):
    """Pydantic schema for setting a company's identity profile -- the
    agent's own name and the company's letterhead/signer default a draft's
    header/signature block falls back to when the writing brief leaves that
    slot unspecified. Every field replaces the profile's current value.
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


class CompanyProfileResponse(BaseModel):
    """Pydantic schema for one company's current identity profile --
    mirrors ``app.ai.identity.company_profile.CompanyProfile`` field-for-field."""

    company_id: str
    version: int
    display_name: str
    short_name: str
    agent_name: str
    letterhead: str
    default_signer_title: str
    updated_at: Optional[str] = None


class CompanyRuleItem(BaseModel):
    """Pydantic schema for one mandatory/recommended drafting rule.

    ``id`` is optional on write: leave it unset for a new rule (the server
    assigns a stable ``Kx`` id) or supply the id an earlier read returned
    to edit that same rule in place -- see
    ``app.domains.companies.provider.set_company_rules``.
    """

    id: Optional[str] = Field(default=None, max_length=20)
    text: str = Field(min_length=1, max_length=300)
    severity: Literal["zorunlu", "onerilen"] = "zorunlu"
    enabled: bool = True


class CompanyRulesUpdate(BaseModel):
    """Pydantic schema for replacing a company's full mandatory rule set."""

    rules: List[CompanyRuleItem] = Field(default_factory=list, max_length=30)


class CompanyRulesResponse(BaseModel):
    """Pydantic schema for one company's current mandatory rule set --
    mirrors ``app.ai.adapters.company_rules.CompanyRuleSet`` field-for-field."""

    company_id: str
    version: int
    rules: List[CompanyRuleItem]
    updated_at: Optional[str] = None
