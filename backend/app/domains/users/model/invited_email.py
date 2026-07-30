from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin

class InvitedEmailModel(Base, TimestampMixin):
    """SQLAlchemy ORM model storing whitelisted/invited emails for registration."""
    __tablename__ = "invited_emails"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="employee")
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
