from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import get_document_analysis_service, require_auth_if_enabled, require_roles
from app.api.responses import APIResponse, SuccessResponse
from app.core.enums.user_role import UserRole
from app.domains.audit.repository import AuditLogRepository
from app.domains.audit.service import AuditService
from app.domains.documents.repository import DocumentRepository
from app.domains.documents.service import DocumentService
from app.domains.pools.repository import DocumentPoolItemRepository, DocumentPoolRepository
from app.domains.pools.schema.pool_schema import (
    DocumentPoolItemResponse,
    DocumentPoolResponse,
    PoolItemCreate,
    PoolPushRequest,
    PoolPushResultItem,
)
from app.domains.pools.service import PoolService
from app.domains.units.repository import UnitMembershipRepository, UnitRepository
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.infrastructure.database.session import get_db
from app.shared.dto.pagination import PaginatedResponse, PaginationParam

router = APIRouter(prefix="/pools", tags=["pools"])


def _audit_service(db: AsyncSession) -> AuditService:
    return AuditService(AuditLogRepository(db))


def _pool_service(db: AsyncSession) -> PoolService:
    return PoolService(
        pool_repository=DocumentPoolRepository(db),
        item_repository=DocumentPoolItemRepository(db),
        document_repository=DocumentRepository(db),
        user_repository=UserRepository(db),
        unit_membership_repository=UnitMembershipRepository(db),
    )


def _item_response(item, document) -> DocumentPoolItemResponse:
    return DocumentPoolItemResponse(
        id=item.id,
        pool_id=item.pool_id,
        document_id=item.document_id,
        file_name=document.file_name if document is not None else None,
        added_by=item.added_by,
        source=item.source,
        note=item.note,
        acknowledged_at=item.acknowledged_at,
        created_at=item.created_at,
    )


@router.get("/me", response_model=APIResponse[DocumentPoolResponse])
async def get_my_pool(
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Çağıranın kendi kişisel evrak havuzu, ilk kullanımda tembel (lazy) olarak oluşturulur."""
    service = _pool_service(db)
    pool = await service.get_or_create_personal_pool(current_user.id, current_user.company_id)
    return SuccessResponse(data=DocumentPoolResponse.model_validate(pool))


@router.get("/{pool_id}/items", response_model=APIResponse[PaginatedResponse])
async def list_pool_items(
    pool_id: str,
    pagination: PaginationParam = Depends(),
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Bir havuzun ögelerini en yeniden en eskiye listeler. Havuzun sahibi veya Admin/Manager/Root."""
    service = _pool_service(db)
    items, total = await service.list_pool_items(
        pool_id, current_user.company_id, current_user, skip=pagination.offset, limit=pagination.limit
    )
    page_items = [_item_response(item, document).model_dump(mode="json") for item, document in items]
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0
    return SuccessResponse(
        data=PaginatedResponse(
            items=page_items, total=total, page=pagination.page, size=pagination.size, pages=pages
        ).model_dump()
    )


@router.post("/{pool_id}/items", response_model=APIResponse[DocumentPoolItemResponse])
async def push_to_pool(
    pool_id: str,
    schema: PoolItemCreate,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Bir evrakı doğrudan belirli, zaten bilinen bir havuza iter (yalnızca Admin/Manager)."""
    service = _pool_service(db)
    item = await service.push_to_pool(
        pool_id, schema.document_id, schema.note, current_user, current_user.company_id
    )
    return SuccessResponse(data=_item_response(item, None).model_dump(mode="json"))


@router.post("/push", response_model=APIResponse[List[PoolPushResultItem]])
async def push_bulk(
    schema: PoolPushRequest,
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Bir evrakı birden çok alıcının (veya bütün bir birimin) kişisel
    havuzlarına iter (yalnızca Admin/Manager). Alıcı bazında sonuç:
    'pushed' | 'denied_clearance' | 'not_found'."""
    service = _pool_service(db)
    results = await service.push(schema, current_user, current_user.company_id)
    await _audit_service(db).record(
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="pool:push",
        resource_type="document",
        resource_id=schema.document_id,
        after={"results": [r.model_dump() for r in results]},
    )
    return SuccessResponse(data=[r.model_dump() for r in results])


@router.delete("/{pool_id}/items/{item_id}", response_model=APIResponse[None])
async def remove_pool_item(
    pool_id: str,
    item_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Havuzdan bir öge kaldırır. Havuzun sahibi veya Admin/Manager/Root."""
    service = _pool_service(db)
    await service.remove_item(pool_id, item_id, current_user.company_id, current_user)
    return SuccessResponse(data=None)


@router.post("/items/{item_id}/acknowledge", response_model=APIResponse[DocumentPoolItemResponse])
async def acknowledge_pool_item(
    item_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """İtilmiş bir ögeyi okundu/onaylandı olarak işaretler. Havuzun sahibi veya Admin/Manager/Root."""
    service = _pool_service(db)
    item = await service.acknowledge_item(item_id, current_user.company_id, current_user)
    return SuccessResponse(data=_item_response(item, None).model_dump(mode="json"))


@router.post("/items/{item_id}/adopt", response_model=APIResponse[DocumentPoolItemResponse])
async def adopt_pool_item(
    item_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
    document_service: DocumentService = Depends(get_document_analysis_service),
):
    """Copy-on-write (Faz 5, #205): bir transferin varsayılan olarak
    bıraktığı salt okunur paylaşılan blob anlık görüntüsü yerine, transfer
    edilen bir ögenin sahibine tamamen bağımsız, düzenlenebilir bir kopya
    (blob + kayıt satırı + analiz önbelleği + Soru-Cevap indeksi) verir.
    Yalnızca havuz ögesinin kendi sahibi -- Admin/Manager atlaması yok,
    bkz. `DocumentService.adopt_pool_item`'in kendi docstring'i."""
    item = await document_service.adopt_pool_item(
        item_id=item_id, current_user=current_user, company_id=current_user.company_id
    )
    document = await DocumentRepository(db).get_by_id(item.document_id, current_user.company_id)
    await _audit_service(db).record(
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="document:adopt",
        resource_type="document",
        resource_id=item.document_id,
        after={"pool_item_id": item.id},
    )
    return SuccessResponse(data=_item_response(item, document).model_dump(mode="json"))
