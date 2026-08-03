from typing import List, Optional

from app.api.exceptions.not_found import NotFoundException
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.repository import DraftRepository


class DraftService:
    """Read-side business logic for the drafts API. Writes happen from
    ChatService, which runs outside a request scope (streaming background
    tasks) and so owns its own session/repository instead of going through
    this service -- see ChatService._persist_draft_version."""

    def __init__(self, repository: DraftRepository):
        self.repository = repository

    async def get_draft(self, draft_id: str) -> DraftModel:
        draft = await self.repository.get_by_id(draft_id)
        if draft is None:
            raise NotFoundException(message="Draft not found.")
        return draft

    async def list_versions(self, draft_id: str) -> List[DraftModel]:
        """Every version in `draft_id`'s conversation, oldest first."""
        draft = await self.get_draft(draft_id)
        return await self.repository.list_versions_for_session(draft.session_id)

    async def list_drafts(
        self,
        *,
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
