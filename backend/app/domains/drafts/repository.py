from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.model.draft_share_model import DraftShareModel


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

    def _latest_version_query(
        self,
        company_id: Optional[str],
        session_id: Optional[str],
        document_id: Optional[str],
        user_id: Optional[str],
    ):
        """The filtered "one row per collapsed chain" query, with no
        ordering/pagination applied -- shared by `list_drafts` (which adds
        `order_by`/`offset`/`limit`) and `count_drafts` (which wraps this in
        `SELECT count()` instead of fetching and `len()`-ing every row)."""
        group_key = func.coalesce(DraftModel.session_id, DraftModel.id)
        latest_version = (
            select(
                group_key.label("group_key"),
                func.max(DraftModel.version).label("max_version"),
            )
            .where(DraftModel.is_deleted.is_(False))
            .group_by(group_key)
            .subquery()
        )
        query = select(DraftModel).join(
            latest_version,
            (group_key == latest_version.c.group_key)
            & (DraftModel.version == latest_version.c.max_version),
        )
        if company_id is not None:
            query = query.where(DraftModel.company_id == company_id)
        if session_id is not None:
            query = query.where(DraftModel.session_id == session_id)
        if document_id is not None:
            query = query.where(DraftModel.document_id == document_id)
        if user_id is not None:
            query = query.where(DraftModel.user_id == user_id)
        return query

    async def list_drafts(
        self,
        company_id: Optional[str] = None,
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

        The grouping key is `COALESCE(session_id, id)`, not bare
        `session_id`. A direct `POST /documents/draft` call (no chat
        session at all -- see `DraftModel.session_id`'s docstring) leaves
        `session_id` `NULL`, and SQL's three-valued logic makes `NULL =
        NULL` evaluate to `NULL`, not `TRUE`: a plain `session_id ==
        session_id` join condition would silently drop *every* such draft
        from this listing, and grouping by bare `session_id` would (via
        `GROUP BY`, which does bucket `NULL`s together, unlike a join
        predicate) collapse every unrelated session-less draft in the
        system into one shared "latest version" -- hiding all but a single
        globally-dominant row, system-wide, once any of them exceeded
        `version=1` (which only became possible once `DraftShareService.
        respond`'s accept-fork could produce one). Falling back to the
        row's own `id` when `session_id` is `NULL` gives every session-less
        draft its own singleton group instead: correct for the common case
        (independent direct drafts, which were never meant to collapse into
        each other), and for an accepted share's forked copy specifically
        -- the fork is owned by a different user than the original (see
        `DraftShareService.respond`), so both showing up as separate rows
        in a company-wide (ADMIN/MANAGER/ROOT) listing is the right
        outcome, not a duplicate to hide.

        `company_id` is `Optional` only because `drafts.company_id` itself
        still is (see `DraftModel.company_id`'s docstring) -- omitted
        entirely rather than filtered to `NULL`, so a caller that hasn't
        adopted tenant scoping yet keeps seeing every company's drafts
        exactly as before, matching every other repository's convention of
        filtering explicitly rather than leaning on row-level security
        alone.
        """
        query = self._latest_version_query(company_id, session_id, document_id, user_id)
        query = query.order_by(DraftModel.updated_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_drafts(
        self,
        company_id: Optional[str] = None,
        session_id: Optional[str] = None,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> int:
        """A real `SELECT count()` over the same collapsed-chain query
        `list_drafts` builds, not a `list_drafts(..., limit=10_000)` +
        `len()` -- the previous approach silently under-counted (and paid
        for) anything past 10,000 rows, the exact anti-pattern
        `DocumentRepository.count_for_owner` was already fixed to avoid."""
        query = self._latest_version_query(company_id, session_id, document_id, user_id)
        result = await self.db.execute(select(func.count()).select_from(query.subquery()))
        return result.scalar_one()

    async def create_version(
        self,
        *,
        user_id: Optional[str],
        company_id: Optional[str] = None,
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
            company_id=company_id,
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


class DraftShareRepository:
    """Repository for `draft_shares` (see `DraftShareModel`).

    Every method takes an explicit `company_id`, same convention as every
    other repository since the tenancy work -- RLS backs this up, it does
    not replace it.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, share_id: str, company_id: str) -> Optional[DraftShareModel]:
        result = await self.db.execute(
            select(DraftShareModel).where(
                DraftShareModel.id == share_id, DraftShareModel.company_id == company_id
            )
        )
        return result.scalar_one_or_none()

    async def create(self, share: DraftShareModel) -> DraftShareModel:
        self.db.add(share)
        await self.db.flush()
        return share

    def _inbox_query(self, company_id: str, user_id: str, status: Optional[str]):
        query = select(DraftShareModel, DraftModel).join(
            DraftModel, DraftModel.id == DraftShareModel.draft_id
        ).where(
            DraftShareModel.company_id == company_id, DraftShareModel.recipient_id == user_id
        )
        if status is not None:
            query = query.where(DraftShareModel.status == status)
        return query

    async def list_inbox(
        self,
        company_id: str,
        user_id: str,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Tuple[DraftShareModel, DraftModel]]:
        """Shares received by `user_id`, newest first, joined with the draft's content."""
        query = (
            self._inbox_query(company_id, user_id, status)
            .order_by(DraftShareModel.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return [(share, draft) for share, draft in result.all()]

    async def count_inbox(self, company_id: str, user_id: str, status: Optional[str] = None) -> int:
        query = select(func.count(DraftShareModel.id)).where(
            DraftShareModel.company_id == company_id, DraftShareModel.recipient_id == user_id
        )
        if status is not None:
            query = query.where(DraftShareModel.status == status)
        result = await self.db.execute(query)
        return result.scalar_one()

    async def list_outbox(
        self,
        company_id: str,
        user_id: str,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Tuple[DraftShareModel, DraftModel]]:
        """Shares sent by `user_id`, newest first, joined with the draft's content."""
        query = select(DraftShareModel, DraftModel).join(
            DraftModel, DraftModel.id == DraftShareModel.draft_id
        ).where(
            DraftShareModel.company_id == company_id, DraftShareModel.sender_id == user_id
        )
        if status is not None:
            query = query.where(DraftShareModel.status == status)
        query = query.order_by(DraftShareModel.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return [(share, draft) for share, draft in result.all()]

    async def count_outbox(self, company_id: str, user_id: str, status: Optional[str] = None) -> int:
        query = select(func.count(DraftShareModel.id)).where(
            DraftShareModel.company_id == company_id, DraftShareModel.sender_id == user_id
        )
        if status is not None:
            query = query.where(DraftShareModel.status == status)
        result = await self.db.execute(query)
        return result.scalar_one()

    async def mark_read(self, share: DraftShareModel) -> DraftShareModel:
        """Advance a still-`sent` share to `read`. A no-op past `sent` (already
        `accepted`/`rejected`/`withdrawn` shares don't regress to `read`)."""
        if share.status == "sent":
            share.status = "read"
        await self.db.flush()
        return share

    async def respond(
        self, share: DraftShareModel, status: str, response_note: Optional[str]
    ) -> DraftShareModel:
        """Resolve a share as `accepted` or `rejected`."""
        share.status = status
        share.response_note = response_note
        share.responded_at = datetime.now(timezone.utc)
        await self.db.flush()
        return share

    async def withdraw(self, share: DraftShareModel) -> DraftShareModel:
        share.status = "withdrawn"
        await self.db.flush()
        return share
