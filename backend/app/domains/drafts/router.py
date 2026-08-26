from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import get_draft_history_service, require_auth_if_enabled
from app.api.exceptions.authorization import AuthorizationException
from app.api.responses import SuccessResponse
from app.core.authz.attributes import Action, Resource
from app.core.authz.dependency import subject_from_user
from app.core.authz.engine import authorize
from app.core.permissions.role_checker import bypasses_ownership
from app.domains.audit.repository import AuditLogRepository
from app.domains.audit.service import AuditService
from app.domains.drafts.draft_share_service import DraftShareService
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.model.draft_share_model import DraftShareModel
from app.domains.drafts.repository import DraftRepository, DraftShareRepository
from app.domains.drafts.schema.draft_schema import DraftDestinationUpdateRequest, DraftResponse
from app.domains.drafts.schema.draft_share_schema import (
    DraftSendRequest,
    DraftShareRespondRequest,
    DraftShareResponse,
)
from app.domains.drafts.service import DraftService
from app.domains.transfers.provider import build_transfer_service
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.infrastructure.database.session import get_db
from app.shared.dto.pagination import PaginatedResponse, PaginationParam

# Kimlik doğrulama zorunludur (bkz. require_auth_if_enabled) -- bu router'daki
# her rota gerçek, kiracıya bağlı bir current_user taşır.
router = APIRouter(
    prefix="/drafts", tags=["drafts"], dependencies=[Depends(require_auth_if_enabled)]
)


def _assert_owns_draft(draft: DraftModel, current_user: UserModel) -> None:
    """Çağıranın sahibi olmadığı bir taslağı geri vermeyi reddeder.

    Eski ``draft.user_id``/``bypasses_ownership`` kontrolünün yerine geçen
    tek bir ABAC kararı (yalın, izinsiz ``engine.authorize`` -- burada
    neden bir DB gidiş-dönüşü olmadığı için bkz.
    ``documents/router.py::_authorize_document``'ın docstring'i).
    ADMIN/MANAGER/ROOT şirket genelinde her taslağı görür, EMPLOYEE yalnızca
    kendisininkini -- eskisiyle aynı sonuç. ``drafts.company_id``,
    ``0016_recorder_tables_rls`` migration'ından beri NOT NULL ve RLS'lidir,
    bu yüzden ``engine.authorize``'ın kiracı kapısı artık burada da gerçek
    bir ikinci kontroldür, boş bir işlem değil.

    Raises:
        AuthorizationException: ``draft.user_id``, ``current_user``'dan
            farklı bir kullanıcıya aitse (ve ADMIN/MANAGER/ROOT değilse).
    """
    resource = Resource(
        type="draft", id=draft.id, company_id=draft.company_id, owner_id=draft.user_id
    )
    decision = authorize(subject_from_user(current_user), Action.DRAFT_READ, resource)
    if not decision.permit:
        raise AuthorizationException(message="Bu taslağa erişim izniniz yok.")


def _assert_can_update_draft(draft: DraftModel, current_user: UserModel) -> None:
    """`_assert_owns_draft` ile aynı biçim, `DRAFT_READ` yerine
    `Action.DRAFT_UPDATE` ile korunur -- sahibi, veya şirket genelinde
    ADMIN/MANAGER/ROOT."""
    resource = Resource(
        type="draft", id=draft.id, company_id=draft.company_id, owner_id=draft.user_id
    )
    decision = authorize(subject_from_user(current_user), Action.DRAFT_UPDATE, resource)
    if not decision.permit:
        raise AuthorizationException(message="Bu taslağı düzenleme izniniz yok.")


@router.get("", response_model=None)
async def list_drafts(
    session_id: Optional[str] = None,
    document_id: Optional[str] = None,
    pagination: PaginationParam = Depends(),
    service: DraftService = Depends(get_draft_history_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Taslakları listeler, oturum başına bir satır (en son sürümü), en
    yeniden en eskiye.

    ``session_id``/``document_id`` listelemeyi daraltır; ``user_id``,
    ``GET /documents``/``GET /chat/sessions`` ile aynı şekilde, çağırandan
    çözümlenir ve bir sorgu parametresi değildir.
    """
    user_id = None if bypasses_ownership(current_user) else current_user.id
    drafts = await service.list_drafts(
        company_id=current_user.company_id,
        session_id=session_id,
        document_id=document_id,
        user_id=user_id,
        skip=pagination.offset,
        limit=pagination.limit,
    )
    total = await service.count_drafts(
        company_id=current_user.company_id,
        session_id=session_id,
        document_id=document_id,
        user_id=user_id,
    )
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0
    paginated = PaginatedResponse(
        items=[DraftResponse.model_validate(draft) for draft in drafts],
        total=total,
        page=pagination.page,
        size=pagination.size,
        pages=pages,
    )
    return SuccessResponse(data=paginated.model_dump(mode="json"))


def _draft_share_service(db: AsyncSession) -> DraftShareService:
    return DraftShareService(
        share_repository=DraftShareRepository(db),
        draft_repository=DraftRepository(db),
        user_repository=UserRepository(db),
        transfer_service=build_transfer_service(db),
    )


def _audit_service(db: AsyncSession) -> AuditService:
    return AuditService(AuditLogRepository(db))


def _share_response(share: DraftShareModel, draft: Optional[DraftModel]) -> DraftShareResponse:
    return DraftShareResponse(
        id=share.id,
        draft_id=share.draft_id,
        sender_id=share.sender_id,
        recipient_id=share.recipient_id,
        suggested_unit_id=share.suggested_unit_id,
        message=share.message,
        status=share.status,
        responded_at=share.responded_at,
        response_note=share.response_note,
        created_at=share.created_at,
        content=draft.content if draft is not None else None,
        correspondence_type=draft.correspondence_type if draft is not None else None,
        destination=draft.destination if draft is not None else None,
    )


# NOT: /inbox ve /outbox aşağıdaki GET /{draft_id}'den önce kaydedilmelidir --
# FastAPI rotaları kayıt sırasına göre eşleştirir ve "/inbox" gibi tek
# segmentli bir yol, o rota zaten önce kaydedildiği için aksi halde
# "/{draft_id}" (draft_id="inbox") tarafından yutulurdu.
@router.get("/inbox", response_model=None)
async def list_draft_inbox(
    status: Optional[str] = None,
    pagination: PaginationParam = Depends(),
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Çağıranın aldığı paylaşımlar, en yeniden en eskiye. İsteğe bağlı
    `status` filtresi ("sent" | "read" | "accepted" | "rejected" | "withdrawn")."""
    service = _draft_share_service(db)
    items, total = await service.list_inbox(
        current_user.company_id, current_user.id, status, pagination.offset, pagination.limit
    )
    page_items = [_share_response(share, draft).model_dump(mode="json") for share, draft in items]
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0
    return SuccessResponse(
        data=PaginatedResponse(
            items=page_items, total=total, page=pagination.page, size=pagination.size, pages=pages
        ).model_dump()
    )


@router.get("/outbox", response_model=None)
async def list_draft_outbox(
    status: Optional[str] = None,
    pagination: PaginationParam = Depends(),
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Çağıranın gönderdiği paylaşımlar, en yeniden en eskiye. İsteğe bağlı `status` filtresi."""
    service = _draft_share_service(db)
    items, total = await service.list_outbox(
        current_user.company_id, current_user.id, status, pagination.offset, pagination.limit
    )
    page_items = [_share_response(share, draft).model_dump(mode="json") for share, draft in items]
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0
    return SuccessResponse(
        data=PaginatedResponse(
            items=page_items, total=total, page=pagination.page, size=pagination.size, pages=pages
        ).model_dump()
    )


@router.get("/{draft_id}", response_model=None)
async def get_draft(
    draft_id: str,
    service: DraftService = Depends(get_draft_history_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Tek bir taslak sürümünü id ile getirir."""
    draft = await service.get_draft(draft_id)
    _assert_owns_draft(draft, current_user)
    return SuccessResponse(data=DraftResponse.model_validate(draft).model_dump(mode="json"))


@router.patch("/{draft_id}/destination", response_model=None)
async def update_draft_destination(
    draft_id: str,
    request: DraftDestinationUpdateRequest,
    service: DraftService = Depends(get_draft_history_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Bu taslak sürümünün yönlendirilmiş birimini çağıranın kendi seçimiyle geçersiz kılar.

    Yönlendirme grafiği artık her zaman birincil (ve genellikle bir
    alternatif) birim öneriyor -- bu, bir insanın bunun yerine üçüncü bir
    seçenek seçtiği yazma yoludur, örn. sohbet arayüzünün birim seçicisinden.
    Satırı yerinde günceller; bir içerik revizyonunun aksine, yönlendirme
    meta verisi taslağın kendi metni olmadığından bu asla yeni bir sürüm
    oluşturmaz.
    """
    draft = await service.get_draft(draft_id)
    _assert_can_update_draft(draft, current_user)
    updated = await service.update_destination(draft_id, request.destination, current_user.company_id)
    return SuccessResponse(data=DraftResponse.model_validate(updated).model_dump(mode="json"))


@router.delete("/{draft_id}", response_model=None)
async def delete_draft(
    draft_id: str,
    service: DraftService = Depends(get_draft_history_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Bir taslağı ve tüm sürüm zincirini geri alınabilir şekilde siler (soft-delete)."""
    draft = await service.get_draft(draft_id)
    _assert_owns_draft(draft, current_user)
    await service.delete_draft(draft_id)
    return SuccessResponse(data={"deleted": True})


@router.get("/{draft_id}/versions", response_model=None)
async def list_draft_versions(
    draft_id: str,
    service: DraftService = Depends(get_draft_history_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Bu taslağın revizyon zincirindeki her sürümü en eskiden en yeniye listeler."""
    draft = await service.get_draft(draft_id)
    _assert_owns_draft(draft, current_user)
    versions = await service.list_versions(draft_id)
    return SuccessResponse(
        data=[
            DraftResponse.model_validate(version).model_dump(mode="json")
            for version in versions
        ]
    )


# ---------------------------------------------------------------------------
# Draft delivery -- çalışanlar arası taslak gönder/al (Faz 5)
# ---------------------------------------------------------------------------


@router.post("/{draft_id}/send", response_model=None)
async def send_draft(
    draft_id: str,
    request: DraftSendRequest,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Bir taslak sürümünü çağıranın şirketi içinde bir veya daha fazla alıcıya gönderir.

    `ArtifactTransferService.execute`'a devreder (bkz. `DraftShareService.
    send`'in kendi docstring'i) -- orada `Action.ARTIFACT_TRANSFER` ile
    korunur: bir EMPLOYEE yalnızca kendi taslağını gönderebilir,
    ADMIN/MANAGER/ROOT şirket genelinde herhangi bir taslağı gönderebilir.
    """
    service = _draft_share_service(db)
    shares = await service.send(draft_id, current_user, request, current_user.company_id)
    audit = _audit_service(db)
    for share in shares:
        await audit.record(
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            actor_role=current_user.role,
            action="draft:share_send",
            resource_type="draft_share",
            resource_id=share.id,
            after={"draft_id": draft_id, "recipient_id": share.recipient_id, "status": share.status},
        )
    return SuccessResponse(data=[_share_response(share, None).model_dump(mode="json") for share in shares])


@router.post("/shares/{share_id}/read", response_model=None)
async def read_draft_share(
    share_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Bir paylaşımı `read` durumuna ilerletir. Yalnızca alıcı."""
    service = _draft_share_service(db)
    share, draft = await service.mark_read(share_id, current_user.company_id, current_user)
    return SuccessResponse(data=_share_response(share, draft).model_dump(mode="json"))


@router.post("/shares/{share_id}/accept", response_model=None)
async def accept_draft_share(
    share_id: str,
    request: DraftShareRespondRequest,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Paylaşılan bir taslağı kabul eder. Yalnızca alıcı -- alıcının artık
    sahibi olduğu yeni bir sürüm çatallar (bkz. `DraftShareService.respond`)."""
    service = _draft_share_service(db)
    share, draft = await service.respond(
        share_id, current_user.company_id, current_user, "accepted", request.response_note
    )
    await _audit_service(db).record(
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="draft:share_accept",
        resource_type="draft_share",
        resource_id=share.id,
        after={"status": share.status},
    )
    return SuccessResponse(data=_share_response(share, draft).model_dump(mode="json"))


@router.post("/shares/{share_id}/reject", response_model=None)
async def reject_draft_share(
    share_id: str,
    request: DraftShareRespondRequest,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Paylaşılan bir taslağı reddeder. Yalnızca alıcı."""
    service = _draft_share_service(db)
    share, draft = await service.respond(
        share_id, current_user.company_id, current_user, "rejected", request.response_note
    )
    await _audit_service(db).record(
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="draft:share_reject",
        resource_type="draft_share",
        resource_id=share.id,
        after={"status": share.status},
    )
    return SuccessResponse(data=_share_response(share, draft).model_dump(mode="json"))


@router.delete("/shares/{share_id}", response_model=None)
async def withdraw_draft_share(
    share_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Hâlâ `sent` durumundaki bir paylaşımı geri çeker. Yalnızca gönderen (veya Admin/Manager/Root)."""
    service = _draft_share_service(db)
    share = await service.withdraw(share_id, current_user.company_id, current_user)
    await _audit_service(db).record(
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="draft:share_withdraw",
        resource_type="draft_share",
        resource_id=share.id,
        after={"status": share.status},
    )
    return SuccessResponse(data=_share_response(share, None).model_dump(mode="json"))
