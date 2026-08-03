from typing import List, Optional
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.drafts.model.draft_model import DraftModel


class DraftRepository:
    """Repository for the append-only draft version history.

    Same shape as UserRepository: the caller owns the AsyncSession (and its
    commit), this class only builds and runs queries against it.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_latest_for_session(self, session_id: str) -> Optional[DraftModel]:
        """The current draft for a conversation: highest `version`, not deleted."""
        result = await self.db.execute(
            select(DraftModel)
            .where(DraftModel.session_id == session_id, DraftModel.is_deleted == False)
            .order_by(DraftModel.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, draft_id: str) -> Optional[DraftModel]:
        result = await self.db.execute(
            select(DraftModel).where(DraftModel.id == draft_id, DraftModel.is_deleted == False)
        )
        return result.scalar_one_or_none()

    async def list_versions_for_session(self, session_id: str) -> List[DraftModel]:
        """Every version for a conversation, oldest first."""
        result = await self.db.execute(
            select(DraftModel)
            .where(DraftModel.session_id == session_id, DraftModel.is_deleted == False)
            .order_by(DraftModel.version.asc())
        )
        return list(result.scalars().all())

    async def list_drafts(
        self,
        *,
        session_id: Optional[str] = None,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[DraftModel]:
        """Latest-version-per-session listing, filtered and paginated.

        Args:
            session_id: Restrict to one conversation.
            document_id: Restrict to drafts sourced from one document.
            user_id: Restrict to one user's drafts.
            skip: Pagination offset.
            limit: Pagination page size.

        Returns:
            The most recent draft of each matching session, newest first --
            this is the "list of draft threads" a future drafts screen shows,
            not every individual revision.
        """
        latest_version = (
            select(
                DraftModel.session_id,
                func.max(DraftModel.version).label("max_version"),
            )
            .where(DraftModel.is_deleted == False)
            .group_by(DraftModel.session_id)
            .subquery()
        )
        query = select(DraftModel).join(
            latest_version,
            (DraftModel.session_id == latest_version.c.session_id)
            & (DraftModel.version == latest_version.c.max_version),
        )
        if session_id:
            query = query.where(DraftModel.session_id == session_id)
        if document_id:
            query = query.where(DraftModel.document_id == document_id)
        if user_id:
            query = query.where(DraftModel.user_id == user_id)
        query = query.order_by(DraftModel.updated_at.desc()).offset(skip).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create_version(
        self,
        *,
        session_id: str,
        content: str,
        user_id: Optional[str] = None,
        document_id: Optional[str] = None,
        correspondence_type: Optional[str] = None,
        routed_unit: Optional[str] = None,
        status: Optional[str] = None,
        confidence_score: Optional[float] = None,
        instructions: Optional[str] = None,
        parent: Optional[DraftModel] = None,
    ) -> DraftModel:
        """Append a new version to a conversation's draft history.

        Args:
            parent: The version this one edits, when known (e.g. the row
                `get_latest_for_session` just returned). `version` and
                `parent_draft_id` are derived from it; omitted for a
                conversation's first draft.

        Returns:
            The newly created, flushed row.
        """
        draft = DraftModel(
            id=str(uuid4()),
            user_id=user_id,
            session_id=session_id,
            document_id=document_id,
            version=(parent.version + 1) if parent else 1,
            parent_draft_id=parent.id if parent else None,
            content=content,
            correspondence_type=correspondence_type,
            routed_unit=routed_unit,
            status=status,
            confidence_score=confidence_score,
            instructions=instructions,
        )
        self.db.add(draft)
        await self.db.flush()
        return draft
