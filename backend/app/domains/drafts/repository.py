from typing import List, Optional
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.drafts.model.draft_model import DraftModel


class DraftRepository:
    """The version-chain registry backing `drafts` (see `DraftModel`)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, draft_id: str) -> Optional[DraftModel]:
        result = await self.db.execute(
            select(DraftModel).where(DraftModel.id == draft_id, DraftModel.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def get_latest_for_session(self, session_id: str) -> Optional[DraftModel]:
        """The most recent version for a session -- "the current draft"."""
        result = await self.db.execute(
            select(DraftModel)
            .where(DraftModel.session_id == session_id, DraftModel.is_deleted.is_(False))
            .order_by(DraftModel.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_versions_for_session(self, session_id: str) -> List[DraftModel]:
        """Every version for a session, oldest first."""
        result = await self.db.execute(
            select(DraftModel)
            .where(DraftModel.session_id == session_id, DraftModel.is_deleted.is_(False))
            .order_by(DraftModel.version.asc())
        )
        return list(result.scalars().all())

    async def list_drafts(
        self,
        session_id: Optional[str] = None,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[DraftModel]:
        """List drafts one row per session -- only each session's latest version.

        Built as a self-join against a per-`session_id` `max(version)`
        subquery rather than `DocumentRepository.count_for_owner`'s
        list-then-len approach, since a draft listing must already collapse
        each session's version chain down to one row and a subquery join
        does that in one query instead of fetching every version.
        """
        latest_version = (
            select(
                DraftModel.session_id.label("session_id"),
                func.max(DraftModel.version).label("max_version"),
            )
            .where(DraftModel.is_deleted.is_(False))
            .group_by(DraftModel.session_id)
            .subquery()
        )
        query = select(DraftModel).join(
            latest_version,
            (DraftModel.session_id == latest_version.c.session_id)
            & (DraftModel.version == latest_version.c.max_version),
        )
        if session_id is not None:
            query = query.where(DraftModel.session_id == session_id)
        if document_id is not None:
            query = query.where(DraftModel.document_id == document_id)
        if user_id is not None:
            query = query.where(DraftModel.user_id == user_id)
        query = query.order_by(DraftModel.updated_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_drafts(
        self,
        session_id: Optional[str] = None,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> int:
        drafts = await self.list_drafts(
            session_id=session_id, document_id=document_id, user_id=user_id, skip=0, limit=10_000
        )
        return len(drafts)

    async def create_version(
        self,
        *,
        user_id: Optional[str],
        session_id: Optional[str],
        document_id: Optional[str],
        content: str,
        parent: Optional[DraftModel] = None,
        correspondence_type: Optional[str] = None,
        destination: Optional[str] = None,
        status: Optional[str] = None,
        confidence_score: Optional[float] = None,
        requires_human_approval: Optional[bool] = None,
        attempts: Optional[int] = None,
        verification: Optional[dict] = None,
        judge: Optional[dict] = None,
        missing_information: Optional[list] = None,
        instructions: Optional[str] = None,
    ) -> DraftModel:
        """Append a new version, chained to `parent` when this is a revision."""
        draft = DraftModel(
            id=uuid4().hex,
            user_id=user_id,
            session_id=session_id,
            document_id=document_id,
            version=(parent.version + 1) if parent is not None else 1,
            parent_draft_id=parent.id if parent is not None else None,
            content=content,
            correspondence_type=correspondence_type,
            destination=destination,
            status=status,
            confidence_score=confidence_score,
            requires_human_approval=requires_human_approval,
            attempts=attempts,
            verification=verification,
            judge=judge,
            missing_information=missing_information,
            instructions=instructions,
        )
        self.db.add(draft)
        await self.db.flush()
        return draft

    async def soft_delete_session(self, session_id: str) -> None:
        """Mark every version in a session's revision chain as deleted.

        `list_drafts` collapses a session down to just its latest version
        (see the `max(version)` subquery above) -- soft-deleting only that
        one row would "resurrect" the previous version as the session's new
        listing, which is not what deleting the draft from the UI means.
        """
        await self.db.execute(
            update(DraftModel)
            .where(DraftModel.session_id == session_id)
            .values(is_deleted=True)
        )
        await self.db.flush()

    async def soft_delete(self, draft_id: str) -> None:
        """Mark a single draft as deleted -- for a `session_id=None` draft
        (a direct `POST /documents/draft` call), where there is no chain to
        collapse."""
        await self.db.execute(
            update(DraftModel).where(DraftModel.id == draft_id).values(is_deleted=True)
        )
        await self.db.flush()
