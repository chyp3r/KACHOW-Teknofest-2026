from typing import List, Optional
from uuid import uuid4

from sqlalchemy import select
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
    ) -> ChatSessionModel:
        """Fetch the session row, creating it on the first turn.

        A later turn only updates `document_id` (the most recently attached
        document) -- `title` and `user_id` are set once, at creation, and
        never overwritten.
        """
        session = await self.get_by_id(session_id)
        if session is not None:
            if document_id is not None:
                session.document_id = document_id
            return session

        session = ChatSessionModel(
            id=session_id, user_id=user_id, document_id=document_id, title=title
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def list_for_user(
        self, user_id: Optional[str], skip: int = 0, limit: int = 100
    ) -> List[ChatSessionModel]:
        """List sessions visible to `user_id`, most recently active first.

        `user_id=None` (the `REQUIRE_AUTH=False` demo/dev path) lists every
        session, matching `DocumentRepository.list_for_owner`'s convention.
        """
        query = select(ChatSessionModel)
        if user_id is not None:
            query = query.where(ChatSessionModel.user_id == user_id)
        query = query.order_by(ChatSessionModel.updated_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_for_user(self, user_id: Optional[str]) -> int:
        sessions = await self.list_for_user(user_id, skip=0, limit=10_000)
        return len(sessions)


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
    ) -> ChatMessageModel:
        message = ChatMessageModel(
            id=uuid4().hex,
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
        """List a session's messages, oldest first (conversation order)."""
        query = (
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_for_session(self, session_id: str) -> int:
        messages = await self.list_for_session(session_id, skip=0, limit=10_000)
        return len(messages)
