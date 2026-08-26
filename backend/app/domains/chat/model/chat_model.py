from typing import Optional

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class ChatSessionModel(Base, TimestampMixin):
    """LangGraph checkpointer thread_id'siyle anahtarlanmış tek bir sohbet konuşması.

    ``id``, ham istemci tarafından sağlanan session_id yerine *birleştirilmiş*
    thread_id'yi saklar (``ChatService._thread_id``, kimlik doğrulanmışsa
    ``f"{user_id}:{session_id}"``), böylece bir oturum satırı
    ``RunModel.thread_id`` ile aynı dize üzerinden join edilebilir. Bu tablo
    salt "bu kullanıcı ne konuştu" sorusunu (listeleme + görüntüleme)
    yanıtlamak için var; duraklatılmış bir iş akışını devam ettirmek için
    gerçek kaynak (source of truth) LangGraph checkpointer'ı olarak kalır.
    """

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: `0016_recorder_tables_rls` migrasyonundan beri NOT NULL --
    #: `PlanningState.company_id`'den `ChatService`'in tur-tamamlama hook'u
    #: üzerinden taşınır, `user_id` ile aynı şekilde.
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    document_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    #: Kırpılmış ilk kullanıcı mesajı -- LLM çağrısından türetilmeyen,
    #: ucuz bir görüntüleme etiketi.
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class ChatMessageModel(Base, TimestampMixin):
    """`ChatSessionModel` içinde bir turluk mesaj (her iki taraf da olabilir).

    Bir tur tamamlandıktan sonra ``app.domains.chat.chat_recorder`` tarafından
    yazılır -- asla istek-kapsamlı DI yolundan değil, çünkü SSE streaming
    endpoint'inin worker görevi, FastAPI'nin dependency-injected session'ından
    daha uzun ömürlüdür (bkz. recorder modülünün kendi docstring'i).
    """

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: Üst (parent) oturumdan denormalize edilmiştir; `0016_recorder_
    #: tables_rls`'den beri NOT NULL -- bkz. `ChatSessionModel.company_id`.
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("chat_sessions.id"), nullable=False, index=True
    )
    #: "user" | "assistant"
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    workflow_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: Asistan turunun ``ChatMessageResponse.details`` payload'ı; kullanıcı
    #: turları için ayarlanmaz.
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
