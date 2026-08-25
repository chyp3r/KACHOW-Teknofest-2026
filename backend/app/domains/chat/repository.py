from typing import List, Optional
from uuid import uuid4

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.chat.model.chat_model import ChatMessageModel, ChatSessionModel


class ChatSessionRepository:
    """The listing registry backing `chat_sessions` (see `ChatSessionModel`)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, session_id: str) -> Optional[ChatSessionModel]:
        result = await self.db.execute(
            select(ChatSessionModel).where(ChatSessionModel.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        session_id: str,
        user_id: Optional[str],
        document_id: Optional[str],
        title: Optional[str],
        company_id: Optional[str] = None,
    ) -> ChatSessionModel:
        """Fetch the session row, creating it on the first turn.

        A later turn only updates `document_id` (the most recently attached
        document) -- `title`/`user_id`/`company_id` are set once, at
        creation, and never overwritten.
        """
        session = await self.get_by_id(session_id)
        if session is not None:
            if document_id is not None:
                session.document_id = document_id
            return session

        session = ChatSessionModel(
            id=session_id,
            user_id=user_id,
            company_id=company_id,
            document_id=document_id,
            title=title,
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def list_for_user(
        self, company_id: Optional[str], user_id: Optional[str], skip: int = 0, limit: int = 100
    ) -> List[ChatSessionModel]:
        """List sessions of `company_id` visible to `user_id`, most recently active first.

        `user_id=None` (an ADMIN/MANAGER/ROOT -- see `bypasses_ownership`)
        lists every session in the company. `company_id` is `Optional` only
        because `chat_sessions.company_id` itself still is (see
        `ChatSessionModel.company_id`'s docstring) -- once migration
        `0016_recorder_tables_rls` makes it `NOT NULL`, every real caller
        always supplies one; explicit filtering here (not left to row-level
        security alone) is the same primary-defense convention every other
        repository follows, e.g. `DocumentRepository.list_for_owner`.
        """
        query = select(ChatSessionModel)
        if company_id is not None:
            query = query.where(ChatSessionModel.company_id == company_id)
        if user_id is not None:
            query = query.where(ChatSessionModel.user_id == user_id)
        query = query.order_by(ChatSessionModel.updated_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_for_user(self, company_id: Optional[str], user_id: Optional[str]) -> int:
        query = select(func.count(ChatSessionModel.id))
        if company_id is not None:
            query = query.where(ChatSessionModel.company_id == company_id)
        if user_id is not None:
            query = query.where(ChatSessionModel.user_id == user_id)
        result = await self.db.execute(query)
        return result.scalar_one()


class ChatMessageRepository:
    """The message log backing `chat_messages` (see `ChatMessageModel`)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        workflow_status: Optional[str] = None,
        details: Optional[dict] = None,
        company_id: Optional[str] = None,
    ) -> ChatMessageModel:
        message = ChatMessageModel(
            id=uuid4().hex,
            company_id=company_id,
            session_id=session_id,
            role=role,
            content=content,
            workflow_status=workflow_status,
            details=details,
        )
        self.db.add(message)
        await self.db.flush()
        return message

    async def list_for_session(
        self, session_id: str, skip: int = 0, limit: int = 200
    ) -> List[ChatMessageModel]:
        """List a session's messages in deterministic conversation order.

        PostgreSQL's ``now()`` is fixed for the whole transaction, so the
        user and assistant rows written by ``record_turn`` have the exact
        same ``created_at`` value. Ordering by that column alone therefore
        let the database return a resume result before its structured user
        response, which exposed the transport summary as a normal chat
        bubble. The role and id tie-breakers preserve the write contract
        (user, then assistant) and make pagination stable for existing rows.
        """
        query = (
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session_id)
            .order_by(
                ChatMessageModel.created_at.asc(),
                case((ChatMessageModel.role == "user", 0), else_=1).asc(),
                ChatMessageModel.id.asc(),
            )
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_for_session(self, session_id: str) -> int:
        result = await self.db.execute(
            select(func.count(ChatMessageModel.id)).where(ChatMessageModel.session_id == session_id)
        )
        return result.scalar_one()
