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
    """Bir listeleme/doğrulama çağrısının fiilen hangi `company_id` üzerinde çalışacağını belirler.

    ROOT herhangi bir `company_id` gönderebilir veya "şirket filtresi yok"
    anlamına gelecek şekilde boş bırakabilir -- bu boş bırakmanın ne yaptığı
    çağırana göre değişir, çünkü `AuditLogRepository.list_filtered` (okuma
    tarafı listeleme filtresi) ile `list_chain`/`verify_chain` (hash-zinciri
    doğrulamasında kullanılan zincir üyeliği) `None` bir `company_id`'yi
    kasıtlı olarak farklı yorumlar; aşağıdaki her router fonksiyonu kendi
    anlamını belgeler. ADMIN burada ne isterse istesin her zaman kendi
    şirketine zorlanır -- bu, bir sorgu parametresinin aksi halde başka bir
    şirketin denetim kaydını okumak için kullanılabileceği tek yerdir, bu
    yüzden ADMIN'den asla güvenilmez.
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
    """Denetim izi kayıtlarını en yeniden en eskiye listeler.

    Root: tek bir şirket için `company_id` gönderin, ya da sistem genelinde
    tüm satırları listelemek için boş bırakın (tüm şirketlerin satırları
    artı root'un kendi sistem geneli işlemleri). Admin: `company_id`'den
    bağımsız olarak her zaman kendi şirketi.
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
    """Tek bir hash zincirini dolaşır ve ilk bozulmuş/eksik halkayı bildirir
    ya da zincirin sağlam olduğunu doğrular.

    Root: o şirketin kendi zinciri için `company_id` gönderin, ya da özellikle
    root'un kendi sistem geneli (`company_id IS NULL`) zincirini doğrulamak
    için boş bırakın -- `GET /audit`'te boş `company_id`'nin "tüm satırlar"
    anlamına gelmesinin aksine, doğrulanacak bir zincir tek bir belirli zincir
    olmak zorundadır, çünkü `seq`/`prev_hash` sürekliliği yalnızca tek bir
    zincir içinde tanımlıdır. Admin: her zaman kendi şirketinin zinciri.
    """
    scoped = _scoped_company_id(current_user, company_id)
    service = _audit_service(db)
    result = await service.verify_chain(scoped)
    return SuccessResponse(data=ChainVerificationResponse(**result.__dict__).model_dump())
