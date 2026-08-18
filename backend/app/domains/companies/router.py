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
    """Root reaches any company; a company admin only reaches their own.

    Manager/employee never reach this router at all -- see the per-route
    ``require_roles`` dependency -- so this only has to distinguish root
    from admin.
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
    """Create a new tenant company (Root only)."""
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
    """List every tenant company, paginated (Root only)."""
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
    """Fetch a single company's details (Root, or that company's own Admin)."""
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
    """Update a company's name/tax number/active flag/settings (Root, or that company's own Admin)."""
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
    """Fetch a company's current runtime style adapter (Faz C2).

    Never 404s for a company with nothing configured -- returns the empty
    adapter shape (``version=0``, empty lists) instead, same as
    ``get_company_adapter`` itself.
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
    """Replace a company's runtime style adapter (Root, or that company's
    own Admin).

    Hand-authoring is the only way to set one today -- Faz C3's automated
    training pipeline will call the same
    ``app.domains.companies.provider.set_company_adapter`` this uses, with
    a real ``sample_count`` instead of the 0 a manual edit gets. Each field
    replaces the adapter's entire list, it does not append.
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
    """Fetch a company's identity profile.

    Never 404s for a company with nothing configured -- returns the empty
    profile shape (``version=0``, empty fields) instead, same as
    ``get_company_adapter_endpoint``.
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
    """Replace a company's identity profile (Root, or that company's own
    Admin). Every field replaces the profile's current value.
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
    """Fetch a company's mandatory drafting rules.

    Never 404s for a company with nothing configured -- returns an empty
    rule list instead, same as ``get_company_adapter_endpoint``.
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
    """Replace a company's mandatory drafting rules (Root, or that
    company's own Admin).

    A violation is graded by the draft-quality judge and, when found,
    becomes a numbered defect the existing verify/revise repair loop fixes
    automatically -- see ``app.ai.verification.llm_judge.judge_draft``'s
    own ``company_rules_block`` parameter.
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
    """Promote an existing company user to Admin (Root only)."""
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
    """Soft-delete a company (Root only)."""
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
