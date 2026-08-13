from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_roles
from app.api.exceptions.authorization import AuthorizationException
from app.api.responses import APIResponse, SuccessResponse
from app.core.enums.user_role import UserRole
from app.domains.companies.repository import CompanyRepository
from app.domains.companies.schema.company_schema import (
    CompanyAdminAssign,
    CompanyCreate,
    CompanyResponse,
    CompanyUpdate,
)
from app.domains.companies.service import CompanyService
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.domains.users.schema.user_schema import UserResponse
from app.infrastructure.database.session import get_db
from app.shared.dto.pagination import PaginatedResponse, PaginationParam

router = APIRouter(prefix="/companies", tags=["companies"])


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
    return SuccessResponse(data=CompanyResponse.model_validate(company))


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
    return SuccessResponse(data=None)
