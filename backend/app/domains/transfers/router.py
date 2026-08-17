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
from app.domains.transfers.schema.transfer_schema import TransferResponse, TransferSendRequest
from app.domains.transfers.service import TransferCommand
from app.domains.units.repository import UnitMembershipRepository, UnitRepository
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserFavoriteRepository
from app.infrastructure.database.session import get_db

# Authentication is mandatory (see require_auth_if_enabled) -- every route in
# this router carries a real, tenant-bound current_user.
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
    """Send one draft or document to one recipient -- the manual chat-
    initiated path. `Action.ARTIFACT_TRANSFER`-gated: an EMPLOYEE may only
    send an artifact it owns, ADMIN/MANAGER/ROOT may send any artifact
    company-wide. Always ends up posting a `kind="artifact"` message into
    the sender/recipient DM (opened if it didn't already exist)."""
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


@router.get("/recommendations", response_model=None)
async def recommend_recipients(
    draft_id: str = Query(...),
    limit: int = Query(default=DEFAULT_RECOMMENDATION_LIMIT, ge=1, le=20),
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Suggested recipients for `draft_id`, ranked from its own routed
    unit's membership (favorites first). Empty, never an error, when the
    draft has no routed unit or that unit is inactive -- a recommendation
    is a hint, not a requirement."""
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
    """Fetch one transfer -- the sender or recipient only (or Admin/
    Manager/Root company-wide), same participation-is-the-grant shape
    `draft_shares` already uses. Backs `ArtifactMessageCard`'s live read of
    a `kind="artifact"` message's current status."""
    transfer = await ArtifactTransferRepository(db).get_by_id(transfer_id, current_user.company_id)
    if transfer is None:
        raise NotFoundException(message="Transfer bulunamadı.")
    if (
        current_user.id not in (transfer.sender_id, transfer.recipient_id)
        and not bypasses_ownership(current_user)
    ):
        raise NotFoundException(message="Transfer bulunamadı.")
    return SuccessResponse(data=_transfer_response(transfer))
