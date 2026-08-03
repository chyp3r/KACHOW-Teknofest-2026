from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_auth_if_enabled
from app.api.responses import APIResponse, SuccessResponse
from app.domains.drafts.repository import DraftRepository
from app.domains.drafts.schema.draft_schema import DraftResponse
from app.domains.drafts.service import DraftService
from app.infrastructure.database.session import get_db

router = APIRouter(
    prefix="/drafts", tags=["drafts"], dependencies=[Depends(require_auth_if_enabled)]
)


@router.get("", response_model=APIResponse[List[DraftResponse]])
async def list_drafts(
    session_id: Optional[str] = Query(default=None),
    document_id: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List the current (latest-version) draft of each matching conversation."""
    service = DraftService(DraftRepository(db))
    drafts = await service.list_drafts(
        session_id=session_id, document_id=document_id, user_id=user_id, skip=skip, limit=limit
    )
    return SuccessResponse(data=[DraftResponse.model_validate(draft) for draft in drafts])


@router.get("/{draft_id}", response_model=APIResponse[DraftResponse])
async def get_draft(draft_id: str, db: AsyncSession = Depends(get_db)):
    """Fetch one specific draft version by id."""
    service = DraftService(DraftRepository(db))
    draft = await service.get_draft(draft_id)
    return SuccessResponse(data=DraftResponse.model_validate(draft))


@router.get("/{draft_id}/versions", response_model=APIResponse[List[DraftResponse]])
async def list_draft_versions(draft_id: str, db: AsyncSession = Depends(get_db)):
    """Every version in `draft_id`'s conversation, oldest first."""
    service = DraftService(DraftRepository(db))
    versions = await service.list_versions(draft_id)
    return SuccessResponse(data=[DraftResponse.model_validate(v) for v in versions])
