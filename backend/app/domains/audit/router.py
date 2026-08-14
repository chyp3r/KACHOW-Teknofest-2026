from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_roles
from app.api.responses import APIResponse, SuccessResponse
from app.core.enums.user_role import UserRole
from app.domains.audit.repository import AuditLogRepository
from app.domains.audit.schema.audit_schema import AuditLogResponse, ChainVerificationResponse
from app.domains.audit.service import AuditService
from app.domains.users.model.user_model import UserModel
from app.infrastructure.database.session import get_db
from app.shared.dto.pagination import PaginatedResponse, PaginationParam

router = APIRouter(prefix="/audit", tags=["audit"])


def _audit_service(db: AsyncSession) -> AuditService:
    return AuditService(AuditLogRepository(db))


def _scoped_company_id(current_user: UserModel, requested_company_id: Optional[str]) -> Optional[str]:
    """Resolve the `company_id` a listing/verify call actually runs against.

    ROOT may pass any `company_id`, or omit it to mean "no company filter" --
    what that omission actually does differs by caller, since
    `AuditLogRepository.list_filtered` (a read-side listing filter) and
    `list_chain`/`verify_chain` (chain-membership, used for hash-chain
    verification) treat a `None` `company_id` differently on purpose; each
    router function below documents its own meaning. ADMIN is always forced
    to its own company here regardless of what it asks for -- this is the
    one place a query parameter could otherwise be used to read another
    company's audit trail, so it is never trusted from ADMIN.
    """
    if current_user.role == UserRole.ROOT.value:
        return requested_company_id
    return current_user.company_id


@router.get("", response_model=APIResponse[PaginatedResponse[AuditLogResponse]])
async def list_audit_log(
    company_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    pagination: PaginationParam = Depends(),
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """List audit trail entries, newest first.

    Root: pass `company_id` for one company, or omit it to list every row
    system-wide (every company's rows plus root's own system-wide actions).
    Admin: always its own company, regardless of `company_id`.
    """
    scoped = _scoped_company_id(current_user, company_id)
    service = _audit_service(db)
    entries = await service.list_entries(
        scoped, actor_user_id, action, resource_type, skip=pagination.offset, limit=pagination.limit
    )
    total = await service.count_entries(scoped, actor_user_id, action, resource_type)
    items = [AuditLogResponse.model_validate(e) for e in entries]
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0
    return SuccessResponse(
        data=PaginatedResponse(
            items=items, total=total, page=pagination.page, size=pagination.size, pages=pages
        ).model_dump(mode="json")
    )


@router.get("/verify", response_model=APIResponse[ChainVerificationResponse])
async def verify_audit_chain(
    company_id: Optional[str] = None,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Walk one hash chain and report the first tampered/missing link, or
    confirm it's intact.

    Root: pass `company_id` for that company's own chain, or omit it to
    verify root's own system-wide (`company_id IS NULL`) chain specifically
    -- unlike `GET /audit`'s omitted-`company_id` meaning "every row," a
    chain to verify has to be one specific chain, since `seq`/`prev_hash`
    continuity is only ever defined within a single chain. Admin: always
    its own company's chain.
    """
    scoped = _scoped_company_id(current_user, company_id)
    service = _audit_service(db)
    result = await service.verify_chain(scoped)
    return SuccessResponse(data=ChainVerificationResponse(**result.__dict__).model_dump())
