from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_auth_if_enabled, require_roles
from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.api.responses import APIResponse, SuccessResponse
from app.core.enums.user_role import UserRole
from app.core.permissions.role_checker import bypasses_ownership
from app.domains.audit.repository import AuditLogRepository
from app.domains.audit.service import AuditService
from app.domains.feedback.repository import FeedbackRepository
from app.domains.feedback.schema.feedback_schema import (
    FeedbackResponse,
    FeedbackStatsResponse,
    FeedbackVoteRequest,
)
from app.domains.feedback.service import FeedbackService
from app.domains.users.model.user_model import UserModel
from app.infrastructure.database.session import get_db
from app.shared.dto.pagination import PaginatedResponse, PaginationParam

# Kimlik doğrulama zorunludur (bkz. require_auth_if_enabled) -- bu router'daki
# her rota gerçek, kiracıya bağlı bir current_user taşır.
router = APIRouter(
    prefix="/feedback", tags=["feedback"], dependencies=[Depends(require_auth_if_enabled)]
)

#: Diğer tüm `/companies/{id}/...` yönetici yüzeyleri gibi okunduğu için
#: burada (/feedback altında değil) kayıtlıdır -- `app.domains.analytics.router`'ın
#: kendi `/companies/{id}/analytics/*`'i ile aynı biçimde.
company_router = APIRouter(prefix="/companies", tags=["feedback"])


def _service(db: AsyncSession) -> FeedbackService:
    return FeedbackService(FeedbackRepository(db))


def _audit_service(db: AsyncSession) -> AuditService:
    return AuditService(AuditLogRepository(db))


def _require_company_access(current_user: UserModel, company_id: str) -> None:
    """Root herhangi bir şirkete erişebilir; Admin/Manager yalnızca kendi şirketine.

    `app.domains.analytics.router._require_company_access` ile aynı kural --
    içe aktarmak yerine tekrarlanmıştır, çünkü o yardımcı fonksiyon kendi
    modülüne özeldir ve bu tek satırlık bir kontroldür.
    """
    if current_user.role == UserRole.ROOT.value:
        return
    if (
        current_user.role in (UserRole.ADMIN.value, UserRole.MANAGER.value)
        and current_user.company_id == company_id
    ):
        return
    raise AuthorizationException(message="Bu şirketin geri bildirim istatistiklerine erişim yetkiniz yok.")


@router.post("", response_model=APIResponse[FeedbackResponse])
async def submit_feedback(
    request: FeedbackVoteRequest,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Yapay zeka tarafından üretilmiş bir çıktıya 👍/👎 oyu verir (veya yeniden verir).

    Kimliği doğrulanmış her kullanıcı, yalnızca kendi şirketiyle sınırlı
    olarak oy verebilir -- bu, RLHF tarzı veri toplama katmanında sadece
    yöneticilerin değil her kullanıcının eriştiği tek yazma yoludur.
    """
    service = _service(db)
    feedback = await service.submit(
        company_id=current_user.company_id,
        user_id=current_user.id,
        target_kind=request.target_kind,
        signal=request.signal,
        content=request.content,
        comment=request.comment,
        dimensions=request.dimensions,
        session_id=request.session_id,
        message_id=request.message_id,
        draft_id=request.draft_id,
        context=request.context,
    )
    await _audit_service(db).record(
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="feedback:submit",
        resource_type="feedback",
        resource_id=feedback.id,
        after={"target_kind": feedback.target_kind, "signal": feedback.signal},
    )
    return SuccessResponse(data=FeedbackResponse.model_validate(feedback).model_dump(mode="json"))


@router.delete("/{feedback_id}", response_model=APIResponse[dict])
async def delete_feedback(
    feedback_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Bir oyu geri çeker. Oyu veren kişi veya şirket genelinde Admin/Manager/Root."""
    service = _service(db)
    feedback = await service.repository.get_by_id(feedback_id, current_user.company_id)
    if feedback is None:
        raise NotFoundException(message="Geri bildirim bulunamadı.")
    if feedback.user_id != current_user.id and not bypasses_ownership(current_user):
        raise AuthorizationException(message="Bu geri bildirimi silme izniniz yok.")
    await service.remove(feedback_id, current_user.company_id)
    await _audit_service(db).record(
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="feedback:delete",
        resource_type="feedback",
        resource_id=feedback_id,
    )
    return SuccessResponse(data={"deleted": True})


@router.get("", response_model=APIResponse[PaginatedResponse[FeedbackResponse]])
async def list_feedback(
    user_id: Optional[str] = None,
    target_kind: Optional[str] = None,
    signal: Optional[str] = None,
    pagination: PaginationParam = Depends(),
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Çağıranın kendi şirketinin geri bildirimlerini en yeniden en eskiye listeler. Yalnızca Admin/Manager/Root."""
    service = _service(db)
    entries = await service.list_entries(
        current_user.company_id, user_id, target_kind, signal,
        skip=pagination.offset, limit=pagination.limit,
    )
    total = await service.count_entries(current_user.company_id, user_id, target_kind, signal)
    items = [FeedbackResponse.model_validate(entry).model_dump(mode="json") for entry in entries]
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0
    return SuccessResponse(
        data=PaginatedResponse(
            items=items, total=total, page=pagination.page, size=pagination.size, pages=pages
        ).model_dump()
    )


@company_router.get(
    "/{company_id}/feedback/stats", response_model=APIResponse[FeedbackStatsResponse]
)
async def feedback_stats(
    company_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Bir şirket için sinyale ve hedef türe göre oy sayıları."""
    _require_company_access(current_user, company_id)
    service = _service(db)
    stats = await service.stats(company_id)
    return SuccessResponse(data=FeedbackStatsResponse(**stats).model_dump())
