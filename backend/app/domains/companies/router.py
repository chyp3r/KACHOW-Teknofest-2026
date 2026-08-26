from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_roles
from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.api.responses import APIResponse, SuccessResponse
from app.core.enums.user_role import UserRole
from app.domains.audit.repository import AuditLogRepository
from app.domains.audit.service import AuditService
from app.domains.companies.provider import (
    get_company_adapter,
    get_company_profile,
    get_company_rules,
    set_company_adapter,
    set_company_profile,
    set_company_rules,
)
from app.domains.companies.repository import CompanyRepository
from app.domains.companies.schema.company_schema import (
    CompanyAdapterResponse,
    CompanyAdapterUpdate,
    CompanyAdminAssign,
    CompanyCreate,
    CompanyProfileResponse,
    CompanyProfileUpdate,
    CompanyResponse,
    CompanyRuleItem,
    CompanyRulesResponse,
    CompanyRulesUpdate,
    CompanyUpdate,
)
from app.domains.companies.service import CompanyService
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.domains.users.schema.user_schema import UserResponse
from app.infrastructure.database.session import get_db
from app.shared.dto.pagination import PaginatedResponse, PaginationParam

router = APIRouter(prefix="/companies", tags=["companies"])


def _audit_service(db: AsyncSession) -> AuditService:
    return AuditService(AuditLogRepository(db))


def _require_company_access(current_user: UserModel, company_id: str) -> None:
    """Root herhangi bir şirkete erişebilir; bir şirket admin'i yalnızca kendi şirketine.

    Manager/employee bu router'a hiçbir zaman ulaşamaz -- bkz. rota başına
    ``require_roles`` bağımlılığı -- bu yüzden bu fonksiyon yalnızca root'u
    admin'den ayırt etmek zorundadır.
    """
    if current_user.role == UserRole.ROOT.value:
        return
    if current_user.role == UserRole.ADMIN.value and current_user.company_id == company_id:
        return
    raise AuthorizationException(message="Bu şirkete erişim yetkiniz yok.")


@router.post("", response_model=APIResponse[CompanyResponse])
async def create_company(
    schema: CompanyCreate,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT)),
    db: AsyncSession = Depends(get_db),
):
    """Yeni bir kiracı şirket oluşturur (yalnızca Root)."""
    service = CompanyService(CompanyRepository(db), UserRepository(db))
    company = await service.create_company(schema, created_by=current_user.id)
    await _audit_service(db).record(
        company_id=company.id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="company:create",
        resource_type="company",
        resource_id=company.id,
        after={"name": company.name, "slug": company.slug},
    )
    return SuccessResponse(data=CompanyResponse.model_validate(company))


@router.get("", response_model=APIResponse[PaginatedResponse[CompanyResponse]])
async def list_companies(
    pagination: PaginationParam = Depends(),
    current_user: UserModel = Depends(require_roles(UserRole.ROOT)),
    db: AsyncSession = Depends(get_db),
):
    """Her kiracı şirketi sayfalanmış şekilde listeler (yalnızca Root)."""
    service = CompanyService(CompanyRepository(db), UserRepository(db))
    companies, total = await service.list_companies(page=pagination.page, size=pagination.size)
    items = [CompanyResponse.model_validate(c) for c in companies]
    pages = (total + pagination.size - 1) // pagination.size if total else 0
    return SuccessResponse(
        data=PaginatedResponse(items=items, total=total, page=pagination.page, size=pagination.size, pages=pages)
    )


@router.get("/{company_id}", response_model=APIResponse[CompanyResponse])
async def get_company(
    company_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Tek bir şirketin ayrıntılarını getirir (Root, veya o şirketin kendi Admin'i)."""
    _require_company_access(current_user, company_id)
    service = CompanyService(CompanyRepository(db), UserRepository(db))
    company = await service.get_company_by_id(company_id)
    return SuccessResponse(data=CompanyResponse.model_validate(company))


@router.patch("/{company_id}", response_model=APIResponse[CompanyResponse])
async def update_company(
    company_id: str,
    schema: CompanyUpdate,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Bir şirketin adını/vergi numarasını/aktiflik durumunu/ayarlarını günceller (Root, veya o şirketin kendi Admin'i)."""
    _require_company_access(current_user, company_id)
    service = CompanyService(CompanyRepository(db), UserRepository(db))
    company = await service.update_company(company_id, schema)
    await _audit_service(db).record(
        company_id=company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="company:update",
        resource_type="company",
        resource_id=company_id,
        after=schema.model_dump(exclude_unset=True, mode="json"),
    )
    return SuccessResponse(data=CompanyResponse.model_validate(company))


def _adapter_response(adapter) -> CompanyAdapterResponse:
    return CompanyAdapterResponse(company_id=adapter.company_id, **adapter.to_dict())


@router.get("/{company_id}/adapter", response_model=APIResponse[CompanyAdapterResponse])
async def get_company_adapter_endpoint(
    company_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
):
    """Bir şirketin geçerli çalışma zamanı stil adaptörünü getirir (Faz C2).

    Hiçbir şey yapılandırılmamış bir şirket için asla 404 döndürmez --
    bunun yerine, ``get_company_adapter``'ın kendisiyle aynı şekilde,
    boş adaptör biçimini (``version=0``, boş listeler) döndürür.
    """
    _require_company_access(current_user, company_id)
    adapter = await get_company_adapter(company_id)
    return SuccessResponse(data=_adapter_response(adapter))


@router.put("/{company_id}/adapter", response_model=APIResponse[CompanyAdapterResponse])
async def update_company_adapter(
    company_id: str,
    schema: CompanyAdapterUpdate,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Bir şirketin çalışma zamanı stil adaptörünü değiştirir (Root, veya o
    şirketin kendi Admin'i).

    Bugün bunu ayarlamanın tek yolu elle yazmaktır -- Faz C3'ün otomatik
    eğitim hattı, manuel bir düzenlemenin aldığı 0 yerine gerçek bir
    ``sample_count`` ile bunun kullandığı aynı
    ``app.domains.companies.provider.set_company_adapter``'ı çağıracaktır.
    Her alan, adaptörün tüm listesinin yerini alır, sona eklemez.
    """
    _require_company_access(current_user, company_id)
    try:
        adapter = await set_company_adapter(
            company_id,
            style_rules=schema.style_rules,
            preferred_examples=schema.preferred_examples,
            avoided_patterns=schema.avoided_patterns,
        )
    except ValueError as exc:
        raise NotFoundException(message="Şirket bulunamadı.") from exc
    await _audit_service(db).record(
        company_id=company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="company:adapter_update",
        resource_type="company_adapter",
        resource_id=company_id,
        after=adapter.to_dict(),
    )
    return SuccessResponse(data=_adapter_response(adapter))


def _profile_response(profile) -> CompanyProfileResponse:
    return CompanyProfileResponse(company_id=profile.company_id, **profile.to_dict())


@router.get("/{company_id}/profile", response_model=APIResponse[CompanyProfileResponse])
async def get_company_profile_endpoint(
    company_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
):
    """Bir şirketin kimlik profilini getirir.

    Hiçbir şey yapılandırılmamış bir şirket için asla 404 döndürmez --
    ``get_company_adapter_endpoint`` ile aynı şekilde, bunun yerine boş
    profil biçimini (``version=0``, boş alanlar) döndürür.
    """
    _require_company_access(current_user, company_id)
    profile = await get_company_profile(company_id)
    return SuccessResponse(data=_profile_response(profile))


@router.put("/{company_id}/profile", response_model=APIResponse[CompanyProfileResponse])
async def update_company_profile(
    company_id: str,
    schema: CompanyProfileUpdate,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Bir şirketin kimlik profilini değiştirir (Root, veya o şirketin kendi
    Admin'i). Her alan, profilin geçerli değerinin yerini alır.
    """
    _require_company_access(current_user, company_id)
    try:
        profile = await set_company_profile(
            company_id,
            display_name=schema.display_name,
            short_name=schema.short_name,
            agent_name=schema.agent_name,
            letterhead=schema.letterhead,
            default_signer_title=schema.default_signer_title,
            default_signer_name=schema.default_signer_name,
            aliases=schema.aliases,
        )
    except ValueError as exc:
        raise NotFoundException(message="Şirket bulunamadı.") from exc
    await _audit_service(db).record(
        company_id=company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="company:profile_update",
        resource_type="company_profile",
        resource_id=company_id,
        after=profile.to_dict(),
    )
    return SuccessResponse(data=_profile_response(profile))


def _rules_response(ruleset) -> CompanyRulesResponse:
    return CompanyRulesResponse(
        company_id=ruleset.company_id,
        version=ruleset.version,
        rules=[CompanyRuleItem(**vars(rule)) for rule in ruleset.rules],
        updated_at=ruleset.updated_at,
    )


@router.get("/{company_id}/rules", response_model=APIResponse[CompanyRulesResponse])
async def get_company_rules_endpoint(
    company_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
):
    """Bir şirketin zorunlu taslak yazım kurallarını getirir.

    Hiçbir şey yapılandırılmamış bir şirket için asla 404 döndürmez --
    ``get_company_adapter_endpoint`` ile aynı şekilde, bunun yerine boş bir
    kural listesi döndürür.
    """
    _require_company_access(current_user, company_id)
    ruleset = await get_company_rules(company_id)
    return SuccessResponse(data=_rules_response(ruleset))


@router.put("/{company_id}/rules", response_model=APIResponse[CompanyRulesResponse])
async def update_company_rules(
    company_id: str,
    schema: CompanyRulesUpdate,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Bir şirketin zorunlu taslak yazım kurallarını değiştirir (Root, veya
    o şirketin kendi Admin'i).

    Bir ihlal, taslak kalite hakemi tarafından derecelendirilir ve
    bulunduğunda, mevcut doğrulama/revizyon onarım döngüsünün otomatik
    olarak düzelttiği numaralandırılmış bir kusur hâline gelir -- bkz.
    ``app.ai.verification.llm_judge.judge_draft``'ın kendi
    ``company_rules_block`` parametresi.
    """
    _require_company_access(current_user, company_id)
    try:
        ruleset = await set_company_rules(
            company_id,
            rules=[item.model_dump() for item in schema.rules],
        )
    except ValueError as exc:
        raise NotFoundException(message="Şirket bulunamadı.") from exc
    await _audit_service(db).record(
        company_id=company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="company:rules_update",
        resource_type="company_rules",
        resource_id=company_id,
        after=ruleset.to_dict(),
    )
    return SuccessResponse(data=_rules_response(ruleset))


@router.post("/{company_id}/admins", response_model=APIResponse[UserResponse])
async def assign_company_admin(
    company_id: str,
    schema: CompanyAdminAssign,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT)),
    db: AsyncSession = Depends(get_db),
):
    """Mevcut bir şirket kullanıcısını Admin'e yükseltir (yalnızca Root)."""
    service = CompanyService(CompanyRepository(db), UserRepository(db))
    user = await service.assign_admin(company_id, schema.user_id)
    await _audit_service(db).record(
        company_id=company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="company:assign_admin",
        resource_type="user",
        resource_id=user.id,
        after={"role": user.role},
    )
    return SuccessResponse(data=UserResponse.model_validate(user))


@router.delete("/{company_id}", response_model=APIResponse[None])
async def delete_company(
    company_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT)),
    db: AsyncSession = Depends(get_db),
):
    """Bir şirketi geri alınabilir şekilde siler (soft-delete) (yalnızca Root)."""
    service = CompanyService(CompanyRepository(db), UserRepository(db))
    await service.delete_company(company_id)
    await _audit_service(db).record(
        company_id=company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="company:delete",
        resource_type="company",
        resource_id=company_id,
    )
    return SuccessResponse(data=None)
