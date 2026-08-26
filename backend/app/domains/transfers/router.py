from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_auth_if_enabled
from app.api.exceptions.not_found import NotFoundException
from app.api.responses import SuccessResponse
from app.core.permissions.role_checker import bypasses_ownership
from app.domains.drafts.repository import DraftRepository
from app.domains.transfers.provider import build_transfer_service
from app.domains.transfers.recommendation import (
    DEFAULT_RECOMMENDATION_LIMIT,
    RecipientRecommendationService,
)
from app.domains.transfers.repository import ArtifactTransferRepository
from app.domains.transfers.schema.transfer_schema import (
    GroupTransferResultItemResponse,
    GroupTransferSendRequest,
    TransferResponse,
    TransferSendRequest,
)
from app.domains.transfers.service import GroupTransferCommand, TransferCommand
from app.domains.units.repository import UnitMembershipRepository, UnitRepository
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserFavoriteRepository
from app.infrastructure.database.session import get_db

# Kimlik doğrulama zorunludur (bkz. require_auth_if_enabled) -- bu router'daki
# her rota gerçek, kiracıya bağlı bir current_user taşır.
router = APIRouter(
    prefix="/transfers", tags=["transfers"], dependencies=[Depends(require_auth_if_enabled)]
)


def _recommendation_service(db: AsyncSession) -> RecipientRecommendationService:
    return RecipientRecommendationService(
        draft_repository=DraftRepository(db),
        unit_repository=UnitRepository(db),
        unit_membership_repository=UnitMembershipRepository(db),
        favorite_repository=UserFavoriteRepository(db),
    )


def _transfer_response(transfer) -> dict:
    return TransferResponse.model_validate(transfer).model_dump(mode="json")


@router.post("/send", response_model=None)
async def send_transfer(
    request: TransferSendRequest,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Bir taslağı veya evrakı tek bir alıcıya gönderir -- manuel, sohbet
    üzerinden başlatılan yol. `Action.ARTIFACT_TRANSFER` ile korunur: bir
    EMPLOYEE yalnızca sahibi olduğu bir artefaktı gönderebilir,
    ADMIN/MANAGER/ROOT şirket genelinde herhangi bir artefaktı gönderebilir.
    Her zaman gönderen/alıcı özel mesajına (yoksa açılarak)
    `kind="artifact"` türünde bir mesaj gönderilmesiyle sonuçlanır."""
    service = build_transfer_service(db)
    transfer = await service.execute(
        TransferCommand(
            company_id=current_user.company_id,
            sender=current_user,
            recipient_id=request.recipient_id,
            artifact_kind=request.artifact_kind,
            source_artifact_id=request.source_artifact_id,
            source_version=request.source_version,
            channel="chat",
            idempotency_key=request.idempotency_key,
        )
    )
    return SuccessResponse(data=_transfer_response(transfer))


@router.post("/send-group", response_model=None)
async def send_group_transfer(
    request: GroupTransferSendRequest,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Bir taslağı veya evrakı birden çok alıcıya aynı anda gönderir --
    yalnızca sohbet/REST üzerinden (yapay zeka kanalının buraya neden hiç
    ulaşmadığı için bkz. `ArtifactTransferService.execute_group`'un kendi
    docstring'i). Alıcı bazında kısmi başarı: bir alıcının reddedilmesi/
    bulunamaması diğerlerini asla engellemez."""
    service = build_transfer_service(db)
    results = await service.execute_group(
        GroupTransferCommand(
            company_id=current_user.company_id,
            sender=current_user,
            recipient_ids=tuple(request.recipient_ids),
            artifact_kind=request.artifact_kind,
            source_artifact_id=request.source_artifact_id,
            source_version=request.source_version,
            idempotency_key_prefix=request.idempotency_key_prefix,
        )
    )
    return SuccessResponse(
        data=[
            GroupTransferResultItemResponse(
                recipient_id=r.recipient_id,
                status=r.status,
                transfer_id=r.transfer_id,
                reason=r.reason,
            ).model_dump(mode="json")
            for r in results
        ]
    )


@router.get("/recommendations", response_model=None)
async def recommend_recipients(
    draft_id: str = Query(...),
    limit: int = Query(default=DEFAULT_RECOMMENDATION_LIMIT, ge=1, le=20),
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """`draft_id` için önerilen alıcılar, taslağın kendi yönlendirilmiş
    biriminin üyeliğinden sıralanmış (favoriler önce). Taslağın yönlendirilmiş
    bir birimi yoksa veya o birim pasifse boş döner, asla hata vermez --
    bir öneri bir ipucudur, bir gereklilik değildir."""
    service = _recommendation_service(db)
    recommendations = await service.recommend_for_draft(
        draft_id, current_user.company_id, current_user.id, limit=limit
    )
    return SuccessResponse(
        data=[
            {
                "user_id": item.user_id,
                "username": item.username,
                "source": item.source,
                "unit_id": item.unit_id,
                "unit_name": item.unit_name,
            }
            for item in recommendations
        ]
    )


@router.get("/{transfer_id}", response_model=None)
async def get_transfer(
    transfer_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Tek bir transferi getirir -- yalnızca gönderen veya alıcı (veya şirket
    genelinde Admin/Manager/Root), `draft_shares`'in zaten kullandığı
    "katılım = yetki" biçimiyle aynı. `ArtifactMessageCard`'ın bir
    `kind="artifact"` mesajının güncel durumunu canlı okumasını destekler."""
    transfer = await ArtifactTransferRepository(db).get_by_id(transfer_id, current_user.company_id)
    if transfer is None:
        raise NotFoundException(message="Transfer bulunamadı.")
    if (
        current_user.id not in (transfer.sender_id, transfer.recipient_id)
        and not bypasses_ownership(current_user)
    ):
        raise NotFoundException(message="Transfer bulunamadı.")
    return SuccessResponse(data=_transfer_response(transfer))
