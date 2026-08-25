from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.model.conversation_message_model import ConversationMessageModel
from app.domains.messaging.model.conversation_model import ConversationModel
from app.domains.messaging.model.conversation_participant_model import ConversationParticipantModel


class ConversationRepository:
    """Repository for `conversations` (see `ConversationModel`).

    Every method takes an explicit `company_id`, same convention as every
    other repository since the tenancy work -- RLS backs this up, it does
    not replace it.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, conversation_id: str, company_id: str) -> Optional[ConversationModel]:
        result = await self.db.execute(
            select(ConversationModel).where(
                ConversationModel.id == conversation_id, ConversationModel.company_id == company_id
            )
        )
        return result.scalar_one_or_none()

    async def get_dm(self, company_id: str, dm_key: str) -> Optional[ConversationModel]:
        """The existing DM for `dm_key`, if one was already opened."""
        result = await self.db.execute(
            select(ConversationModel).where(
                ConversationModel.company_id == company_id,
                ConversationModel.kind == "dm",
                ConversationModel.dm_key == dm_key,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, conversation: ConversationModel) -> ConversationModel:
        self.db.add(conversation)
        await self.db.flush()
        return conversation

    async def list_for_user(
        self, company_id: str, user_id: str, skip: int = 0, limit: int = 50
    ) -> List[Tuple[ConversationModel, ConversationParticipantModel]]:
        """Conversations `user_id` actively participates in (has not left),
        newest activity first. `last_message_at` is NULL for a brand new
        conversation with no messages yet -- those sort last via NULLS LAST.
        """
        query = (
            select(ConversationModel, ConversationParticipantModel)
            .join(
                ConversationParticipantModel,
                ConversationParticipantModel.conversation_id == ConversationModel.id,
            )
            .where(
                ConversationModel.company_id == company_id,
                ConversationParticipantModel.company_id == company_id,
                ConversationParticipantModel.user_id == user_id,
                ConversationParticipantModel.left_at.is_(None),
            )
            .order_by(ConversationModel.last_message_at.desc().nullslast(), ConversationModel.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return [(conversation, participant) for conversation, participant in result.all()]

    async def count_for_user(self, company_id: str, user_id: str) -> int:
        query = (
            select(func.count(ConversationModel.id))
            .join(
                ConversationParticipantModel,
                ConversationParticipantModel.conversation_id == ConversationModel.id,
            )
            .where(
                ConversationModel.company_id == company_id,
                ConversationParticipantModel.company_id == company_id,
                ConversationParticipantModel.user_id == user_id,
                ConversationParticipantModel.left_at.is_(None),
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one()

    async def touch_last_message(self, conversation: ConversationModel, at: datetime) -> None:
        """Denormalize the newest message's timestamp onto the conversation
        row, so listing never needs a per-row aggregate join."""
        conversation.last_message_at = at
        await self.db.flush()

    async def update(self, conversation: ConversationModel, update_data: dict) -> ConversationModel:
        for field, value in update_data.items():
            if hasattr(conversation, field) and value is not None:
                setattr(conversation, field, value)
        await self.db.flush()
        return conversation


class ConversationParticipantRepository:
    """Repository for `conversation_participants` -- the access grant itself
    (see `ConversationParticipantModel`'s docstring)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(
        self, conversation_id: str, user_id: str, company_id: str
    ) -> Optional[ConversationParticipantModel]:
        """The participant row for `user_id`, whether active or left --
        callers deciding *read* access want this (a former participant may
        still read history); callers deciding *write* access must also
        check `left_at is None` themselves."""
        result = await self.db.execute(
            select(ConversationParticipantModel).where(
                ConversationParticipantModel.conversation_id == conversation_id,
                ConversationParticipantModel.user_id == user_id,
                ConversationParticipantModel.company_id == company_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_conversation(
        self, conversation_id: str, company_id: str, active_only: bool = False
    ) -> List[ConversationParticipantModel]:
        query = select(ConversationParticipantModel).where(
            ConversationParticipantModel.conversation_id == conversation_id,
            ConversationParticipantModel.company_id == company_id,
        )
        if active_only:
            query = query.where(ConversationParticipantModel.left_at.is_(None))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(self, participant: ConversationParticipantModel) -> ConversationParticipantModel:
        self.db.add(participant)
        await self.db.flush()
        return participant

    async def create_many(
        self, participants: List[ConversationParticipantModel]
    ) -> List[ConversationParticipantModel]:
        self.db.add_all(participants)
        await self.db.flush()
        return participants

    async def mark_left(self, participant: ConversationParticipantModel, at: datetime) -> ConversationParticipantModel:
        participant.left_at = at
        await self.db.flush()
        return participant

    async def mark_read(
        self, participant: ConversationParticipantModel, message_id: str
    ) -> ConversationParticipantModel:
        participant.last_read_message_id = message_id
        await self.db.flush()
        return participant


class ConversationMessageRepository:
    """Repository for `conversation_messages` (see `ConversationMessageModel`)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, message: ConversationMessageModel) -> ConversationMessageModel:
        self.db.add(message)
        await self.db.flush()
        return message

    async def get_by_id(self, message_id: str, company_id: str) -> Optional[ConversationMessageModel]:
        result = await self.db.execute(
            select(ConversationMessageModel).where(
                ConversationMessageModel.id == message_id,
                ConversationMessageModel.company_id == company_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_conversation(
        self,
        conversation_id: str,
        company_id: str,
        before_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[ConversationMessageModel]:
        """Keyset page of messages, newest first. `before_id` (a message id
        already seen by the caller) resolves to that message's own
        `(created_at, id)` and returns strictly older rows -- offset-based
        pagination would double-count/skip rows as new messages arrive
        between page fetches, which a live thread does constantly."""
        query = select(ConversationMessageModel).where(
            ConversationMessageModel.conversation_id == conversation_id,
            ConversationMessageModel.company_id == company_id,
            ConversationMessageModel.deleted_at.is_(None),
        )
        if before_id is not None:
            cursor = await self.get_by_id(before_id, company_id)
            if cursor is not None:
                query = query.where(
                    tuple_(ConversationMessageModel.created_at, ConversationMessageModel.id)
                    < tuple_(cursor.created_at, cursor.id)
                )
        query = query.order_by(
            ConversationMessageModel.created_at.desc(), ConversationMessageModel.id.desc()
        ).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_unread(
        self,
        conversation_id: str,
        company_id: str,
        user_id: str,
        last_read_message_id: Optional[str],
    ) -> int:
        """Unread messages received by `user_id`.

        A user's own messages are never unread for that user. System-authored
        messages have no sender and remain countable. The read cursor compares
        `created_at`, not the id itself -- message ids are opaque uuid-hex, not
        ordered.
        """
        base = select(func.count(ConversationMessageModel.id)).where(
            ConversationMessageModel.conversation_id == conversation_id,
            ConversationMessageModel.company_id == company_id,
            ConversationMessageModel.deleted_at.is_(None),
            or_(
                ConversationMessageModel.sender_id.is_(None),
                ConversationMessageModel.sender_id != user_id,
            ),
        )
        if last_read_message_id is None:
            result = await self.db.execute(base)
            return result.scalar_one()

        cursor = await self.get_by_id(last_read_message_id, company_id)
        if cursor is None:
            result = await self.db.execute(base)
            return result.scalar_one()

        result = await self.db.execute(base.where(ConversationMessageModel.created_at > cursor.created_at))
        return result.scalar_one()
