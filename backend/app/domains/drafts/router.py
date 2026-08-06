from typing import Optional

from fastapi import APIRouter, Depends

from app.api.dependency import get_draft_history_service, require_auth_if_enabled
from app.api.exceptions.authorization import AuthorizationException
from app.api.responses import SuccessResponse
from app.core.permissions.role_checker import bypasses_ownership
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.schema.draft_schema import DraftResponse
from app.domains.drafts.service import DraftService
from app.domains.users.model.user_model import UserModel
from app.shared.dto.pagination import PaginatedResponse, PaginationParam

# See require_auth_if_enabled / settings.REQUIRE_AUTH: a no-op by default so
# the demo works without the frontend implementing a login flow.
router = APIRouter(
    prefix="/drafts", tags=["drafts"], dependencies=[Depends(require_auth_if_enabled)]
)


def _assert_owns_draft(draft: DraftModel, current_user: Optional[UserModel]) -> None:
    """Refuse to hand back a draft the caller doesn't own.

    ``current_user=None`` (``REQUIRE_AUTH`` off) skips the check entirely,
    matching every other route in this codebase. ADMIN/MANAGER see every
    draft company-wide, the same as ``bypasses_ownership`` everywhere else.

    Raises:
        AuthorizationException: If ``draft.user_id`` belongs to a different
            user than ``current_user`` (and it isn't an ADMIN/MANAGER).
    """
    if current_user is None:
        return
    if draft.user_id != current_user.id and not bypasses_ownership(current_user):
        raise AuthorizationException(message="Bu taslağa erişim izniniz yok.")


@router.get("", response_model=None)
async def list_drafts(
    session_id: Optional[str] = None,
    document_id: Optional[str] = None,
    pagination: PaginationParam = Depends(),
    service: DraftService = Depends(get_draft_history_service),
    current_user: Optional[UserModel] = Depends(require_auth_if_enabled),
):
    """List drafts, one row per session (its latest version), newest first.

    ``session_id``/``document_id`` narrow the listing; ``user_id`` is
    resolved from the caller and is not a query parameter, same as
    ``GET /documents``/``GET /chat/sessions``.
    """
    user_id = (
        current_user.id if current_user and not bypasses_ownership(current_user) else None
    )
    drafts = await service.list_drafts(
        session_id=session_id,
        document_id=document_id,
        user_id=user_id,
        skip=pagination.offset,
        limit=pagination.limit,
    )
    total = await service.count_drafts(
        session_id=session_id, document_id=document_id, user_id=user_id
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


@router.get("/{draft_id}", response_model=None)
async def get_draft(
    draft_id: str,
    service: DraftService = Depends(get_draft_history_service),
    current_user: Optional[UserModel] = Depends(require_auth_if_enabled),
):
    """Fetch one draft version by id."""
    draft = await service.get_draft(draft_id)
    _assert_owns_draft(draft, current_user)
    return SuccessResponse(data=DraftResponse.model_validate(draft).model_dump(mode="json"))


@router.get("/{draft_id}/versions", response_model=None)
async def list_draft_versions(
    draft_id: str,
    service: DraftService = Depends(get_draft_history_service),
    current_user: Optional[UserModel] = Depends(require_auth_if_enabled),
):
    """List every version in this draft's revision chain, oldest first."""
    draft = await service.get_draft(draft_id)
    _assert_owns_draft(draft, current_user)
    versions = await service.list_versions(draft_id)
    return SuccessResponse(
        data=[
            DraftResponse.model_validate(version).model_dump(mode="json")
            for version in versions
        ]
    )
