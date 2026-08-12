from typing import List, Optional

from app.api.exceptions.not_found import NotFoundException
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.repository import DraftRepository


class DraftService:
    """Business logic for the drafts API.

    Creation happens through `app.domains.drafts.draft_recorder`, called
    from `app.domains.documents.draft_service.DraftService.
    generate_draft_and_route` and from `ChatService` -- both run outside a
    request-scoped session (the latter during SSE streaming), so they own
    their own session/repository instead of going through this service.
    `delete_draft` is the one write this service does own: it runs inside
    the request-scoped session the drafts router already has, with no
    SSE-streaming concern to route around.
    """

    def __init__(self, repository: DraftRepository) -> None:
        self.repository = repository

    async def get_draft(self, draft_id: str) -> DraftModel:
        draft = await self.repository.get_by_id(draft_id)
        if draft is None:
            raise NotFoundException(message="Draft not found.")
        return draft

    async def list_versions(self, draft_id: str) -> List[DraftModel]:
        """Every version in the draft's chain, oldest first.

        Looks the draft up first purely to resolve its `session_id` --
        version chains for a direct-API draft (`session_id=None`) collapse
        to just that one draft, since there is nothing to chain it to.
        """
        draft = await self.get_draft(draft_id)
        if draft.session_id is None:
            return [draft]
        return await self.repository.list_versions_for_session(draft.session_id)

    async def list_drafts(
        self,
        session_id: Optional[str] = None,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[DraftModel]:
        return await self.repository.list_drafts(
            session_id=session_id,
            document_id=document_id,
            user_id=user_id,
            skip=skip,
            limit=limit,
        )

    async def count_drafts(
        self,
        session_id: Optional[str] = None,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> int:
        return await self.repository.count_drafts(
            session_id=session_id, document_id=document_id, user_id=user_id
        )

    async def delete_draft(self, draft_id: str) -> None:
        """Soft-delete a draft, and the whole version chain it belongs to.

        Raises:
            NotFoundException: If `draft_id` doesn't exist (or is already
                deleted -- `get_by_id` filters `is_deleted`, so a second
                delete call is reported the same as a missing draft rather
                than silently succeeding).
        """
        draft = await self.get_draft(draft_id)
        if draft.session_id is None:
            await self.repository.soft_delete(draft_id)
        else:
            await self.repository.soft_delete_session(draft.session_id)
