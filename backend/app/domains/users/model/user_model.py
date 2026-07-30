from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin

class UserModel(Base, TimestampMixin):
    """SQLAlchemy ORM model for user accounts supporting role-based authorization."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="employee")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
