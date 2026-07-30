class ChatModel:
    """Skeletal SQLAlchemy model for chat sessions."""
    __tablename__ = "chat_sessions"
    id: str
    user_id: str
