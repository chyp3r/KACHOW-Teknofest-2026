from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.model.conversation_message_model import ConversationMessageModel
from app.domains.messaging.model.conversation_model import ConversationModel
from app.domains.messaging.model.conversation_participant_model import ConversationParticipantModel


class ConversationRepository:
    """`conversations` için repository (bkz. `ConversationModel`).

    Her metot açık bir `company_id` alır, tenancy çalışmasından bu yana
    diğer tüm repository'lerle aynı kural -- RLS bunu destekler, yerine
    geçmez.
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
        """`dm_key` için zaten açılmış olan mevcut DM (varsa)."""
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
        """`user_id`'nin aktif olarak katıldığı (ayrılmadığı) konuşmalar,
        en yeni etkinlik önce. Henüz hiç mesajı olmayan yepyeni bir
        konuşma için `last_message_at` NULL'dır -- bunlar NULLS LAST ile
        en sona sıralanır.
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
        """En yeni mesajın zaman damgasını conversation satırına
        denormalize eder, böylece listeleme hiçbir zaman satır başına
        aggregate join gerektirmez."""
        conversation.last_message_at = at
        await self.db.flush()

    async def update(self, conversation: ConversationModel, update_data: dict) -> ConversationModel:
        for field, value in update_data.items():
            if hasattr(conversation, field) and value is not None:
                setattr(conversation, field, value)
        await self.db.flush()
        return conversation


class ConversationParticipantRepository:
    """`conversation_participants` için repository -- erişim izninin
    kendisi (bkz. `ConversationParticipantModel`'in docstring'i)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(
        self, conversation_id: str, user_id: str, company_id: str
    ) -> Optional[ConversationParticipantModel]:
        """`user_id` için katılımcı satırı, aktif ya da ayrılmış farketmez
        -- *okuma* erişimine karar veren çağıranlar bunu ister (eski bir
        katılımcı geçmişi hâlâ okuyabilir); *yazma* erişimine karar veren
        çağıranlar ayrıca kendileri `left_at is None` kontrolü yapmalıdır."""
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
    """`conversation_messages` için repository (bkz. `ConversationMessageModel`)."""

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
        """Mesajların keyset sayfası, en yeni önce. `before_id` (çağıran
        tarafından zaten görülmüş bir mesaj id'si) o mesajın kendi
        `(created_at, id)` değerine çözümlenir ve kesinlikle daha eski
        satırları döndürür -- offset tabanlı sayfalama, sayfa alımları
        arasında yeni mesajlar geldikçe satırları çift sayar/atlar, ki
        canlı bir thread bunu sürekli yapar."""
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
        self, conversation_id: str, company_id: str, last_read_message_id: Optional[str]
    ) -> int:
        """`last_read_message_id`'den daha yeni mesajlar (veya hiç
        okunmamışsa tüm mesajlar). Id'nin kendisini değil `created_at`'i
        karşılaştırır -- mesaj id'leri sıralı değil, opak uuid-hex'tir."""
        base = select(func.count(ConversationMessageModel.id)).where(
            ConversationMessageModel.conversation_id == conversation_id,
            ConversationMessageModel.company_id == company_id,
            ConversationMessageModel.deleted_at.is_(None),
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
