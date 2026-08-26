from typing import List, Optional
from uuid import uuid4

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.chat.model.chat_model import ChatMessageModel, ChatSessionModel


class ChatSessionRepository:
    """`chat_sessions`'ın arkasındaki listeleme kaydı (bkz. `ChatSessionModel`)."""

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
        """Oturum satırını getir, ilk turda oluştur.

        Sonraki bir tur yalnızca `document_id`'yi (en son eklenen belgeyi)
        günceller -- `title`/`user_id`/`company_id` bir kez, oluşturma
        anında ayarlanır ve asla üzerine yazılmaz.
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
        """`user_id`'nin görebildiği `company_id`'nin oturumlarını, en son aktif olan önce sırayla listele.

        `user_id=None` (bir ADMIN/MANAGER/ROOT -- bkz. `bypasses_ownership`)
        şirketteki her oturumu listeler. `company_id`'nin `Optional` olması
        yalnızca `chat_sessions.company_id`'nin kendisinin hâlâ öyle olması
        yüzünden (bkz. `ChatSessionModel.company_id`'nin docstring'i) --
        `0016_recorder_tables_rls` migrasyonu onu `NOT NULL` yaptığında,
        her gerçek çağıran her zaman bir tane sağlar; buradaki açık
        filtreleme (yalnızca satır düzeyi güvenliğe bırakılmadan) diğer
        her repository'nin izlediği aynı birincil-savunma kuralıdır,
        ör. `DocumentRepository.list_for_owner`.
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
    """`chat_messages`'ın arkasındaki mesaj günlüğü (bkz. `ChatMessageModel`)."""

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
        """Bir oturumun mesajlarını, belirli bir sırayla (konuşma sırasıyla) listele.

        PostgreSQL'in ``now()``'ı tüm transaction boyunca sabittir, bu yüzden
        ``record_turn``'ün yazdığı user ve assistant satırları tam olarak
        aynı ``created_at`` değerine sahip olur. Yalnızca bu sütuna göre
        sıralamak, veritabanının yapılandırılmış user cevabından önce bir
        resume sonucunu döndürmesine izin veriyordu, bu da transport
        özetini normal bir sohbet balonu olarak açığa çıkarıyordu. role ve
        id eşitlik bozucuları yazma sözleşmesini (önce user, sonra
        assistant) korur ve mevcut satırlar için sayfalamayı kararlı hale
        getirir.
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
