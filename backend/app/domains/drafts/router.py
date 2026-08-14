from typing import Optional

from fastapi import APIRouter, Depends

from app.api.dependency import get_draft_history_service, require_auth_if_enabled
from app.api.exceptions.authorization import AuthorizationException
from app.api.responses import SuccessResponse
from app.core.authz.attributes import Action, Resource
from app.core.authz.dependency import subject_from_user
from app.core.authz.engine import authorize
from app.core.permissions.role_checker import bypasses_ownership
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.schema.draft_schema import DraftResponse
from app.domains.drafts.service import DraftService
from app.domains.users.model.user_model import UserModel
from app.shared.dto.pagination import PaginatedResponse, PaginationParam

# Authentication is mandatory (see require_auth_if_enabled) -- every route in
# this router carries a real, tenant-bound current_user.
router = APIRouter(
    prefix="/drafts", tags=["drafts"], dependencies=[Depends(require_auth_if_enabled)]
)


def _assert_owns_draft(draft: DraftModel, current_user: UserModel) -> None:
    """Refuse to hand back a draft the caller doesn't own.

    Single ABAC decision (bare, grant-less ``engine.authorize`` -- see
    ``documents/router.py::_authorize_document``'s docstring for why no DB
    round trip here) replacing the old ``draft.user_id``/
    ``bypasses_ownership`` check. ADMIN/MANAGER/ROOT see every draft
    company-wide, EMPLOYEE only its own -- same outcome as before.
    ``drafts.company_id`` is NOT NULL and RLS'd since migration
    ``0016_recorder_tables_rls``, so ``engine.authorize``'s tenant gate is
    now a real second check here too, not a no-op.

    Raises:
        AuthorizationException: If ``draft.user_id`` belongs to a different
            user than ``current_user`` (and it isn't ADMIN/MANAGER/ROOT).
    """
    resource = Resource(
        type="draft", id=draft.id, company_id=draft.company_id, owner_id=draft.user_id
    )
    decision = authorize(subject_from_user(current_user), Action.DRAFT_READ, resource)
    if not decision.permit:
        raise AuthorizationException(message="Bu taslağa erişim izniniz yok.")


@router.get("", response_model=None)
async def list_drafts(
    session_id: Optional[str] = None,
    document_id: Optional[str] = None,
    pagination: PaginationParam = Depends(),
    service: DraftService = Depends(get_draft_history_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """List drafts, one row per session (its latest version), newest first.

    ``session_id``/``document_id`` narrow the listing; ``user_id`` is
    resolved from the caller and is not a query parameter, same as
    ``GET /documents``/``GET /chat/sessions``.
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


@router.get("/{draft_id}", response_model=None)
async def get_draft(
    draft_id: str,
    service: DraftService = Depends(get_draft_history_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Fetch one draft version by id."""
    draft = await service.get_draft(draft_id)
    _assert_owns_draft(draft, current_user)
    return SuccessResponse(data=DraftResponse.model_validate(draft).model_dump(mode="json"))


@router.delete("/{draft_id}", response_model=None)
async def delete_draft(
    draft_id: str,
    service: DraftService = Depends(get_draft_history_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Soft-delete a draft and its whole version chain."""
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
